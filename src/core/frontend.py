"""Integração do frontend estático (prototipos-telas-chamados-unifap) sem alterar seus arquivos.

Serve `frontend/index.html` na raiz injetando `/bridge.js` em memória na resposta HTTP,
conectando o estado síncrono `window.DB` do protótipo aos endpoints reais `/api/v1/*`.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

BRIDGE_JS = r"""/* Ponte não-invasiva entre window.DB (frontend) e a API FastAPI (/api/v1/*). */
(function () {
  'use strict';
  if (!window.DB) return;

  const TOKEN_KEY = 'unifap-api-jwt';
  const MAP_KEY = 'unifap-api-protocolos';
  const SENHA_SEED = 'Unifap@2026';

  // Mapeamento dos perfis do protótipo para as matrículas da API (memória ou Supabase)
  const MATRICULAS_MEMORIA = {
    gestor: '40000001',
    executor_ti: '30000002',
    executor: '30000001',
    solicitante: '20230001',
    inativo: '20190002'
  };
  const MATRICULAS_SUPABASE = {
    gestor: '1987654',
    executor_ti: '1987654',
    executor: '1987654',
    solicitante: '2021001234',
    inativo: '2021001234'
  };

  let modoPersistencia = 'memoria';
  let catalogoLocais = [];
  let catalogoCategorias = [];

  async function detectarModo() {
    try {
      const r = await fetch('/api/v1/info');
      if (r.ok) {
        const d = await r.json();
        modoPersistencia = d.persistencia || 'memoria';
      }
    } catch (e) { /* segue padrao */ }
  }

  function normTxt(s) {
    return String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
  }

  function localApi(ambId) {
    if (catalogoLocais.length) {
      // 1) O ambiente já é um código real do catálogo do backend
      const direto = catalogoLocais.find(l => l.id === ambId);
      if (direto) return direto.id;
      // 2) Ambiente legado do protótipo: casa pelo nome exato (ex.: "Sala B-204")
      const p = DB.localPartes(ambId);
      if (p) {
        const porNome = catalogoLocais.find(l => normTxt(l.nome) === normTxt(p.ambiente.nome));
        if (porNome) return porNome.id;
      }
      // 3) Último recurso: mesmo tipo de ambiente
      const tipo = p ? (p.ambiente.tipo || '').toLowerCase() : '';
      const alvoTipo = tipo.includes('laborat') ? 'LABORATORIO'
        : tipo.includes('audit') ? 'AUDITORIO'
        : tipo.includes('sala') ? 'SALA' : 'AREA_COMUM';
      const achado = catalogoLocais.find(l => l.tipo === alvoTipo) || catalogoLocais[0];
      return achado.id;
    }
    return ambId;
  }

  const TIPO_LOCAL_FRONT = {
    SALA: 'Sala de aula', LABORATORIO: 'Laboratório', AUDITORIO: 'Auditório', AREA_COMUM: 'Área comum'
  };

  function slugId(s) { return normTxt(s).replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'x'; }

  // Substitui o catálogo fictício do protótipo pelo catálogo real (Supabase/backend),
  // para que o local escolhido no formulário seja exatamente o local salvo no chamado.
  function aplicarCatalogoNoFront() {
    if (!catalogoLocais.length) return false;
    const campi = [], blocos = [], andares = [], ambientes = [];
    const vistos = new Set();
    const ordenados = catalogoLocais.slice().sort((a, b) =>
      String(a.campus || '').localeCompare(String(b.campus || ''), 'pt-BR')
      || String(a.bloco).localeCompare(String(b.bloco), 'pt-BR')
      || (a.andar - b.andar)
      || String(a.nome).localeCompare(String(b.nome), 'pt-BR', { numeric: true }));
    for (const l of ordenados) {
      const campusNome = l.campus || 'Campus principal';
      const cid = 'c-' + slugId(campusNome);
      if (!vistos.has(cid)) { vistos.add(cid); campi.push({ id: cid, nome: campusNome, codigo: campusNome.slice(0, 3).toUpperCase(), ativo: true }); }
      const bid = cid + '--b-' + slugId(l.bloco);
      if (!vistos.has(bid)) { vistos.add(bid); blocos.push({ id: bid, campus: cid, nome: l.bloco, codigo: l.bloco, ativo: true }); }
      const aid = bid + '--a-' + l.andar;
      if (!vistos.has(aid)) { vistos.add(aid); andares.push({ id: aid, bloco: bid, nome: l.andar === 0 ? 'Térreo' : l.andar + 'º andar', ativo: true }); }
      ambientes.push({ id: l.id, andar: aid, nome: l.nome, codigo: l.id, tipo: TIPO_LOCAL_FRONT[l.tipo] || 'Área comum', ativo: true });
    }
    const antes = JSON.stringify(DB.s.ambientes.map(a => a.id));
    DB.s.campi = campi; DB.s.blocos = blocos; DB.s.andares = andares; DB.s.ambientes = ambientes;
    return antes !== JSON.stringify(ambientes.map(a => a.id));
  }

  async function garantirCatalogo(forcar) {
    let mudouCatalogo = false;
    if (forcar || !catalogoLocais.length) {
      const rl = await api('GET', '/catalogo/locais');
      if (rl.ok && Array.isArray(rl.data) && rl.data.length) {
        catalogoLocais = rl.data;
        mudouCatalogo = aplicarCatalogoNoFront();
      }
    }
    if (forcar || !catalogoCategorias.length) {
      const rc = await api('GET', '/catalogo/categorias');
      if (rc.ok && Array.isArray(rc.data)) catalogoCategorias = rc.data;
    }
    return mudouCatalogo;
  }

  function categoriaApi(catId) {
    if (catalogoCategorias.length) {
      const pistas = {
        eletrica: 'ELETRIC',
        refrig: 'REFRIG',
        ti: 'TECNOLOGIA',
        predial: 'PREDIAL',
        limpeza: 'LIMPEZA',
        jardim: 'PREDIAL'
      };
      const pista = pistas[catId] || '';
      const catFront = DB.cat(catId);
      const achada = (catFront && catalogoCategorias.find(c => normTxt(c.nome) === normTxt(catFront.nome)))
        || catalogoCategorias.find(c =>
          (pista && c.id.includes(pista)) || (catId === 'refrig' && c.id.includes('CLIMAT')) || (catId === 'ti' && c.id === 'TI')
        ) || catalogoCategorias[0];
      return achada.id;
    }
    return 'ELETRICA';
  }

  function matriculaParaUsuario(u) {
    if (!u) return null;
    const mapa = modoPersistencia === 'supabase' ? MATRICULAS_SUPABASE : MATRICULAS_MEMORIA;
    if (!u.vinculoAtivo) return mapa.inativo;
    if (u.perfis.includes('gestor') || u.perfis.includes('admin') || u.perfis.includes('reitoria')) {
      return mapa.gestor;
    }
    if (u.perfis.includes('executor')) {
      return (u.setor || '').toLowerCase().includes('tecnologia') ? mapa.executor_ti : mapa.executor;
    }
    return mapa.solicitante;
  }

  function executorIdApi(uId) {
    if (uId && /^[0-9a-f-]{32,36}$/i.test(uId)) return uId;
    const exeReal = DB.s.usuarios.find(u => u.perfis.includes('executor') && /^[0-9a-f-]{32,36}$/i.test(u.id));
    if (exeReal) return exeReal.id;
    const u = uId && DB.user(uId);
    if (u && (u.setor || '').toLowerCase().includes('tecnologia')) return 'u-exe-2';
    return 'u-exe-1';
  }

  function loadMap() {
    try { return JSON.parse(sessionStorage.getItem(MAP_KEY) || '{}'); } catch (e) { return {}; }
  }
  function saveMap(m) {
    try { sessionStorage.setItem(MAP_KEY, JSON.stringify(m)); } catch (e) { /* ok */ }
  }
  function getToken() {
    try { return sessionStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; }
  }
  function setToken(t) {
    try {
      if (t) sessionStorage.setItem(TOKEN_KEY, t);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch (e) { /* ok */ }
  }

  async function api(method, path, body) {
    const headers = { 'Content-Type': 'application/json' };
    const tok = getToken();
    if (tok) headers.Authorization = 'Bearer ' + tok;
    let res;
    try {
      res = await fetch('/api/v1' + path, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined
      });
    } catch (e) {
      const falha = { ok: false, status: 0, data: { mensagem: 'Sem conexão com o servidor. Verifique sua internet e tente novamente.' } };
      if (window.UnifapApi) window.UnifapApi.ultimo = { method, path, status: 0, data: falha.data };
      return falha;
    }
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
    if (window.UnifapApi) window.UnifapApi.ultimo = { method, path, status: res.status, data };
    return { ok: res.ok, status: res.status, data };
  }

  function mensagemErro(r, padrao) {
    if (!r) return padrao;
    if (r.status === 401) return 'Sua sessão expirou. Saia e entre novamente para continuar.';
    if (r.status === 403) return (r.data && r.data.mensagem) || 'Seu perfil não tem permissão para esta ação.';
    if (r.status === 429) return 'Muitas tentativas em pouco tempo. Aguarde alguns segundos e tente de novo.';
    const d = r.data;
    if (d && typeof d === 'object') {
      if (d.mensagem) return d.mensagem;
      if (Array.isArray(d.detalhes) && d.detalhes.length) return d.detalhes.map(x => x.msg || x.mensagem || String(x)).join(' ');
      if (Array.isArray(d.detail) && d.detail.length) return d.detail.map(x => x.msg || String(x)).join(' ');
    }
    return padrao;
  }

  function avisar(r, padrao) {
    if (r && !r.ok && window.UI && UI.toast) UI.toast(mensagemErro(r, padrao), 'err');
    return !!(r && r.ok);
  }

  const STATUS_API_PARA_FRONT = {
    ABERTO: 'triagem',
    ATRIBUIDO: 'atribuido',
    EM_ATENDIMENTO: 'atendimento',
    RESOLVIDO: 'resolvido',
    REABERTO: 'reencaminhado',
    FECHADO: 'concluido',
    CANCELADO: 'cancelado'
  };

  const PRIO_API_PARA_FRONT = {
    BAIXA: 'baixa',
    MEDIA: 'media',
    ALTA: 'alta',
    CRITICA: 'alta'
  };

  function categoriaParaFront(catApi) {
    const s = String(catApi || '').toUpperCase();
    if (s.includes('ELETRIC')) return 'eletrica';
    if (s.includes('REFRIG') || s.includes('CLIMAT')) return 'refrig';
    if (s.includes('TECNOLOGIA') || s === 'TI') return 'ti';
    if (s.includes('LIMPEZA')) return 'limpeza';
    return 'predial';
  }

  function ambienteParaFront(localApiId) {
    const s = String(localApiId || '').toUpperCase();
    if (DB.amb(s)) return s;
    if (DB.amb(localApiId)) return localApiId;
    if (s.includes('204')) return 'mz-b-2-x1';
    if (s.includes('LAB1')) return 'mz-c-1-x1';
    if (s.includes('LAB2')) return 'mz-c-1-x1';
    if (s.includes('LABQ')) return 'mz-c-0-x1';
    if (s.includes('AUD')) return 'mz-a-0-x1';
    return (DB.s.ambientes[0] && DB.s.ambientes[0].id) || 'mz-b-2-x1';
  }

  function garantirUsuarioLocal(id, nomeFallback) {
    if (!id) return;
    if (!DB.user(id)) {
      DB.s.usuarios.push({
        id,
        nome: nomeFallback || 'Usuário UNIFAP',
        login: id.slice(0, 8),
        ident: id.slice(0, 8),
        tipo: 'Discente',
        vinculoAtivo: true,
        acessoAtivo: true,
        perfis: ['solicitante'],
        setor: ''
      });
    }
  }

  let sincronizando = false;
  let escritasEmAndamento = 0;
  let geracaoEscrita = 0;
  let ressincronizar = false;
  let renderPendente = false;

  // Verdadeiro quando o usuário está preenchendo algum formulário na tela atual.
  // Nesses casos a atualização periódica NÃO pode redesenhar a tela (apagaria o que foi digitado).
  function telaComEdicao() {
    if (document.querySelector('dialog[open]')) return true;
    const main = document.getElementById('main');
    if (!main) return false;
    if (main.querySelector('[data-submit]:disabled')) return true;
    const ae = document.activeElement;
    if (ae && main.contains(ae) && /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName) && ae.type !== 'file') return true;
    if (main.querySelector('[data-files] li')) return true;
    for (const el of main.querySelectorAll('input, textarea, select')) {
      if (el.disabled || el.type === 'file' || el.type === 'hidden') continue;
      if (el.tagName === 'SELECT') {
        const opts = [...el.options];
        const temPadrao = opts.some(o => o.defaultSelected);
        if (temPadrao ? opts.some(o => o.selected !== o.defaultSelected) : el.selectedIndex > 0) return true;
      } else if (el.type === 'checkbox' || el.type === 'radio') {
        if (el.checked !== el.defaultChecked) return true;
      } else if (el.value !== el.defaultValue) {
        return true;
      }
    }
    return false;
  }

  function renderSeguro() {
    if (!(window.App && App.render)) return;
    if (telaComEdicao()) { renderPendente = true; return; }
    renderPendente = false;
    const y = window.scrollY;
    App.render();
    window.scrollTo(0, y);
  }

  // Atualiza os chamados existentes NO MESMO OBJETO (preserva referências usadas pelas telas abertas,
  // evitando que ações feitas depois de uma sincronização sejam perdidas).
  function mesclarChamados(reais) {
    const existentes = new Map(DB.s.chamados.map(c => [c.id, c]));
    return reais.map(r => {
      const ex = existentes.get(r.id);
      if (!ex) return r;
      for (const k of Object.keys(ex)) if (!(k in r)) delete ex[k];
      Object.assign(ex, r);
      return ex;
    });
  }

  async function carregarChamadosDoBackend() {
    if (!getToken()) return;
    if (sincronizando || escritasEmAndamento > 0) { ressincronizar = true; return; }
    sincronizando = true;
    ressincronizar = false;
    const geracaoInicial = geracaoEscrita;
    const obsoleto = () => escritasEmAndamento > 0 || geracaoInicial !== geracaoEscrita;
    try {
      // Só consulta /usuarios quando o perfil atual for admin (evita 403 desnecessários)
      if (DB.can('admin')) {
        const ru = await api('GET', '/usuarios');
        if (ru.ok && Array.isArray(ru.data)) {
          DB.s.usuarios = ru.data.map(u => ({
            id: u.id, nome: u.nome, login: u.matricula, ident: u.matricula, email: u.email,
            tipo: u.perfil === 'SOLICITANTE' ? 'Discente' : 'Servidor',
            vinculoAtivo: u.vinculo_ativo, acessoAtivo: u.vinculo_ativo,
            perfis: u.perfil === 'ADMIN' ? ['admin', 'gestor', 'solicitante']
              : u.perfil === 'GESTOR' ? ['gestor', 'solicitante']
              : u.perfil === 'EXECUTOR' ? ['executor', 'solicitante'] : ['solicitante'],
            setor: u.setor || ''
          }));
        }
      }

      const rl = await api('GET', '/chamados?limite=100');
      if (!rl.ok || !Array.isArray(rl.data) || obsoleto()) return;

      const mapa = loadMap();

      async function montarChamado(resumo) {
        const proto = resumo.protocolo;
        const [rd, rh] = await Promise.all([
          api('GET', '/chamados/' + encodeURIComponent(proto)),
          api('GET', '/chamados/' + encodeURIComponent(proto) + '/historico')
        ]);
        if (!rd.ok || !rd.data) return null;
        const d = rd.data;
        const histApi = rh.ok && Array.isArray(rh.data) ? rh.data : [];

        garantirUsuarioLocal(d.solicitante_id, 'Solicitante');
        if (d.executor_id) garantirUsuarioLocal(d.executor_id, 'Executor');

        const historicoFront = histApi.map(h => {
          garantirUsuarioLocal(h.ator_id, 'Equipe');
          return {
            em: h.registrado_em,
            autor: h.ator_id,
            tipo: h.acao === 'AVALIACAO_FECHAMENTO' ? 'avaliacao'
              : h.acao.includes('COMENTARIO') ? 'comentario' : 'estado',
            texto: h.detalhe ? `${h.acao}: ${h.detalhe}` : h.acao,
            publico: !h.acao.includes('INTERNO') && h.acao !== 'OBSERVACAO_ATRIBUICAO'
          };
        });
        if (!historicoFront.length) {
          historicoFront.push({
            em: d.criado_em, autor: d.solicitante_id, tipo: 'estado',
            texto: 'Chamado registrado no sistema.', publico: true
          });
        }

        const catFront = categoriaParaFront(d.categoria_id);
        const catObj = DB.cat(catFront);
        return {
          id: proto,
          categoria: catFront,
          ambiente: ambienteParaFront(d.local_id),
          autor: d.solicitante_id,
          impedeAula: !!d.impacta_aulas,
          prioridade: PRIO_API_PARA_FRONT[d.prioridade] || 'media',
          estado: STATUS_API_PARA_FRONT[d.status] || 'triagem',
          descricao: d.descricao || d.titulo,
          criadoEm: d.criado_em,
          equipe: d.executor_id && catObj ? catObj.setor : '',
          executor: d.executor_id || '',
          anexos: (d.evidencias || []).map(e => ({
            apiId: e.id,
            nome: e.nome_arquivo,
            tipo: (e.content_type || '').startsWith('video') ? 'video' : 'image',
            tamanho: +(e.tamanho_bytes / 1048576).toFixed(1) || 0.1
          })),
          avaliacao: d.avaliacao ? { nota: d.avaliacao.nota, comentario: d.avaliacao.comentario || '' } : undefined,
          historico: historicoFront
        };
      }

      // Busca os detalhes em lotes paralelos (evita dezenas de requisições em série)
      const reais = [];
      const LOTE = 6;
      for (let i = 0; i < rl.data.length; i += LOTE) {
        if (obsoleto()) return;
        const parte = await Promise.all(rl.data.slice(i, i + LOTE).map(montarChamado));
        for (const c of parte) {
          if (!c) continue;
          reais.push(c);
          mapa[c.id] = c.id;
        }
      }

      if (obsoleto()) return;
      saveMap(mapa);
      const mudou = JSON.stringify(DB.s.chamados) !== JSON.stringify(reais);
      if (mudou) {
        DB.s.chamados = mesclarChamados(reais);
        originalSave();
        anterior = snapshot();
        renderSeguro();
      }
    } catch (err) {
      console.warn('[UNIFAP Bridge sync]', err);
    } finally {
      sincronizando = false;
      if (ressincronizar) {
        ressincronizar = false;
        setTimeout(() => { carregarChamadosDoBackend().catch(() => {}); }, 400);
      }
    }
  }

  async function autenticarSessao(userId) {
    if (!userId || !getToken()) return;
    await detectarModo();
    const mudouCatalogo = await garantirCatalogo(true);
    if (mudouCatalogo) { originalSave(); renderSeguro(); }
    await carregarChamadosDoBackend();
  }

  function payloadChamado(c) {
    const cat = DB.cat(c.categoria);
    const titulo = ((cat ? cat.nome : 'Chamado') + ' - ' + DB.localCurto(c.ambiente)).slice(0, 120);
    const desc = c.descricao && c.descricao.length >= 10
      ? c.descricao
      : (c.descricao || '') + ' (detalhamento adicional registrado)';
    return {
      titulo: titulo.length >= 5 ? titulo : 'Chamado UNIFAP',
      descricao: (desc === titulo ? desc + '.' : desc).slice(0, 2000),
      local_id: localApi(c.ambiente),
      categoria_id: categoriaApi(c.categoria),
      equipamento: null,
      impacta_aulas: !!c.impedeAula,
      pessoas_afetadas: c.impedeAula ? 30 : 5
    };
  }

  async function enviarEvidencias(protocolo, itens) {
    const tok = getToken();
    const anexos = [];
    let falhas = 0;
    for (const item of itens || []) {
      if (item.raw && tok) {
        try {
          const fd = new FormData();
          fd.append('arquivo', item.raw, item.name);
          const rUp = await fetch('/api/v1/chamados/' + encodeURIComponent(protocolo) + '/evidencias', {
            method: 'POST', headers: { Authorization: 'Bearer ' + tok }, body: fd
          });
          if (!rUp.ok) { falhas += 1; continue; }
          const d = await rUp.json().catch(() => ({}));
          if (d && d.id) {
            window.UnifapMediaCache = window.UnifapMediaCache || {};
            try { window.UnifapMediaCache[protocolo + ':' + d.id] = URL.createObjectURL(item.raw); } catch (e) { /* ok */ }
          }
          anexos.push({ apiId: d.id || null, nome: item.name, tipo: item.video ? 'video' : 'image', tamanho: +(item.size / 1048576).toFixed(1) || 0.1 });
        } catch (e) { falhas += 1; }
      } else if (item.driveUrl) {
        const rGd = await api('POST', '/chamados/' + encodeURIComponent(protocolo) + '/evidencias/google-drive', {
          url: item.driveUrl,
          nome_arquivo: item.name
        });
        if (!rGd.ok) { falhas += 1; continue; }
        const d = rGd.data || {};
        anexos.push({ apiId: d.id || null, nome: d.nome_arquivo || item.name, tipo: String(d.content_type || '').startsWith('video') ? 'video' : 'image', tamanho: +((d.tamanho_bytes || 0) / 1048576).toFixed(1) || 0.1 });
      }
    }
    return { anexos, falhas };
  }

  // Criação síncrona usada pela tela "Abrir chamado": só confirma ao usuário depois que o
  // backend salvou de fato. Em caso de erro, o formulário permanece preenchido.
  async function criarChamadoApi(dados) {
    if (!getToken()) {
      return { ok: false, mensagem: 'Sua sessão expirou. Saia e entre novamente para enviar o chamado.' };
    }
    escritasEmAndamento += 1;
    geracaoEscrita += 1;
    try {
      await garantirCatalogo(false);
      const r = await api('POST', '/chamados', payloadChamado(dados));
      if (!r.ok || !r.data || !r.data.protocolo) {
        return { ok: false, mensagem: mensagemErro(r, 'Não foi possível registrar o chamado no servidor. Seus dados foram mantidos; tente novamente.') };
      }
      const protocolo = r.data.protocolo;
      const mapa = loadMap();
      mapa[protocolo] = protocolo;
      saveMap(mapa);
      const up = await enviarEvidencias(protocolo, dados.arquivos);
      return {
        ok: true,
        protocolo,
        prioridade: PRIO_API_PARA_FRONT[r.data.prioridade] || null,
        criadoEm: r.data.criado_em || null,
        anexos: up.anexos,
        falhas: up.falhas
      };
    } finally {
      escritasEmAndamento = Math.max(0, escritasEmAndamento - 1);
    }
  }

  async function sincronizarNovoChamado(c) {
    const mapa = loadMap();
    if (mapa[c.id]) return;
    await garantirCatalogo(false);
    const r = await api('POST', '/chamados', payloadChamado(c));
    if (!r.ok || !r.data || !r.data.protocolo) {
      avisar(r, 'Não foi possível salvar o chamado no servidor.');
      return;
    }
    const protocolo = r.data.protocolo;
    mapa[c.id] = protocolo;
    mapa[protocolo] = protocolo;
    saveMap(mapa);
    const pendentes = (window.UnifapPendingUploads && window.UnifapPendingUploads[c.id]) || [];
    if (pendentes.length) {
      delete window.UnifapPendingUploads[c.id];
      const up = await enviarEvidencias(protocolo, pendentes);
      if (up.falhas && window.UI && UI.toast) {
        UI.toast(up.falhas + ' evidência(s) não puderam ser salvas no servidor. Tente anexar novamente nos detalhes do chamado.', 'err');
      }
    }
  }

  async function sincronizarAlteracao(antes, depois) {
    const mapa = loadMap();
    const protocolo = mapa[depois.id];
    if (!protocolo) return;

    if (antes.estado !== depois.estado) {
      if (depois.estado === 'atribuido') {
        const obsEv = depois.historico.slice(antes.historico.length).find(h => h.publico === false);
        const rAt = await api('POST', '/triagem/' + protocolo + '/atribuir', {
          executor_id: executorIdApi(depois.executor),
          observacao: obsEv ? obsEv.texto : null
        });
        avisar(rAt, 'Falha ao salvar atribuição no servidor.');
      } else if (depois.estado === 'atendimento') {
        const rIn = await api('POST', '/chamados/' + protocolo + '/iniciar');
        avisar(rIn, 'Falha ao iniciar atendimento no servidor.');
      } else if (depois.estado === 'resolvido') {
        const sol = depois.historico.slice(antes.historico.length).find(h => h.tipo === 'comentario');
        const texto = sol && sol.texto.length >= 10 ? sol.texto : 'Atendimento concluído pela equipe técnica.';
        const rRes = await api('POST', '/chamados/' + protocolo + '/resolver', { solucao: texto });
        avisar(rRes, 'Falha ao registrar resolução no servidor.');
      } else if (depois.estado === 'concluido') {
        const nota = depois.avaliacao && depois.avaliacao.nota ? depois.avaliacao.nota : 5;
        const com = depois.avaliacao && depois.avaliacao.comentario
          ? depois.avaliacao.comentario
          : (!depois.avaliacao ? 'Concluído pelo solicitante sem nota.' : null);
        const rAv = await api('POST', '/chamados/' + protocolo + '/avaliacao', {
          nota,
          comentario: com
        });
        avisar(rAv, 'Não foi possível registrar a avaliação no servidor.');
      } else if (depois.estado === 'reencaminhado') {
        const rRe = await api('POST', '/triagem/' + protocolo + '/reencaminhar', {
          motivo: 'Reencaminhado pela equipe técnica para nova triagem.'
        });
        avisar(rRe, 'Falha ao reencaminhar chamado no servidor.');
      } else if (depois.estado === 'cancelado') {
        const rCa = await api('POST', '/chamados/' + protocolo + '/cancelar', {
          motivo: 'Cancelado pelo usuário na interface.'
        });
        avisar(rCa, 'Falha ao cancelar chamado no servidor.');
      }
      return;
    }

    // Novo comentário interno sem mudança de estado
    if (depois.historico.length > antes.historico.length) {
      const novos = depois.historico.slice(antes.historico.length);
      for (const h of novos) {
        if (h.tipo === 'comentario' && h.texto) {
          const rCm = await api('POST', '/chamados/' + protocolo + '/comentarios', {
            texto: h.texto,
            interno: h.publico === false
          });
          avisar(rCm, 'Falha ao registrar comentário no servidor.');
        }
      }
    }
  }

  function snapshot() {
    return {
      sessao: DB.s.sessao,
      chamados: DB.s.chamados.map(c => ({
        id: c.id,
        estado: c.estado,
        executor: c.executor,
        historicoLen: c.historico.length,
        historico: c.historico.slice(),
        avaliacao: c.avaliacao || null
      }))
    };
  }

  let anterior = snapshot();
  const originalSave = DB.save.bind(DB);

  DB.save = function () {
    originalSave();
    const atual = snapshot();
    const prev = anterior;
    anterior = atual;

    (async () => {
      const mudouSessao = prev.sessao !== atual.sessao;
      const prevById = new Map(prev.chamados.map(c => [c.id, c]));
      const pendentesNovos = [];
      const pendentesAlt = [];
      const mapaAtual = loadMap();
      for (const c of DB.s.chamados) {
        const antes = prevById.get(c.id);
        if (!antes) {
          if (!mapaAtual[c.id]) pendentesNovos.push(c);
        } else if (antes.estado !== c.estado || antes.historicoLen !== c.historico.length) {
          pendentesAlt.push([antes, c]);
        }
      }

      const temEscrita = pendentesNovos.length > 0 || pendentesAlt.length > 0;
      if (temEscrita) {
        escritasEmAndamento += 1;
        geracaoEscrita += 1;
      }
      try {
        if (mudouSessao) {
          await autenticarSessao(atual.sessao);
        }
        for (const c of pendentesNovos) {
          await sincronizarNovoChamado(c);
        }
        for (const [antes, c] of pendentesAlt) {
          await sincronizarAlteracao(antes, c);
        }
      } catch (err) {
        console.warn('[UNIFAP Bridge]', err);
      } finally {
        if (temEscrita) {
          escritasEmAndamento = Math.max(0, escritasEmAndamento - 1);
          carregarChamadosDoBackend().catch(() => {});
        }
      }
    })();
  };

  if (DB.s.sessao && getToken()) {
    autenticarSessao(DB.s.sessao).catch(() => {});
  }
  window.addEventListener('hashchange', () => {
    renderPendente = false;
    if (DB.s.sessao && getToken()) carregarChamadosDoBackend().catch(() => {});
  });
  setInterval(() => {
    if (DB.s.sessao && getToken() && !document.hidden) {
      carregarChamadosDoBackend().catch(() => {});
    }
  }, 15000);

  window.UnifapApi = {
    get token() { return getToken(); },
    get protocolos() { return loadMap(); },
    sincronizar: carregarChamadosDoBackend,
    criarChamado: criarChamadoApi,
    garantirCatalogo,
    ultimo: null,
    api
  };
})();
"""


def montar_frontend(
    app: FastAPI,
    diretorio: Path = FRONTEND_DIR,
    *,
    habilitar_bridge_demo: bool = True,
) -> bool:
    """Registra rotas do frontend se o diretório existir, sem alterar arquivos originais.

    V21: em produção (`habilitar_bridge_demo=False`), não injeta `/bridge.js` com
    auto-login/senha de demonstração.
    """
    index_path = diretorio / "index.html"
    if not index_path.is_file():
        return False

    html_original = index_path.read_text(encoding="utf-8")
    marcador = '<script src="js/data.js?v=24"></script>'
    injetado = marcador + '\n  <script src="/bridge.js"></script>'
    html_integrado = (
        html_original.replace(marcador, injetado, 1)
        if marcador in html_original
        else html_original.replace("</body>", '  <script src="/bridge.js"></script>\n</body>', 1)
    )
    html_servido = html_integrado if habilitar_bridge_demo else html_original

    @app.get("/", include_in_schema=False)
    def frontend_index() -> HTMLResponse:
        return HTMLResponse(content=html_servido)

    if habilitar_bridge_demo:
        @app.get("/bridge.js", include_in_schema=False)
        def frontend_bridge() -> Response:
            return Response(content=BRIDGE_JS, media_type="application/javascript; charset=utf-8")

    for pasta in ("css", "js", "assets"):
        sub = diretorio / pasta
        if sub.is_dir():
            app.mount(f"/{pasta}", StaticFiles(directory=str(sub)), name=f"frontend-{pasta}")

    return True
