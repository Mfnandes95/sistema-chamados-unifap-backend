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

  function localApi(ambId) {
    if (catalogoLocais.length) {
      const p = DB.localPartes(ambId);
      const tipo = p ? (p.ambiente.tipo || '').toLowerCase() : '';
      const alvoTipo = tipo.includes('laborat') ? 'LABORATORIO'
        : tipo.includes('audit') ? 'AUDITORIO'
        : tipo.includes('sala') ? 'SALA' : 'AREA_COMUM';
      const achado = catalogoLocais.find(l => l.tipo === alvoTipo) || catalogoLocais[0];
      return achado.id;
    }
    return 'BL1-T-S101';
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
      const achada = catalogoCategorias.find(c =>
        c.id.includes(pista) || (catId === 'refrig' && c.id.includes('CLIMAT')) || (catId === 'ti' && c.id === 'TI')
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
    const res = await fetch('/api/v1' + path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined
    });
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
    window.UnifapApi.ultimo = { method, path, status: res.status, data };
    return { ok: res.ok, status: res.status, data };
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

  async function carregarChamadosDoBackend() {
    if (!getToken() || sincronizando) return;
    sincronizando = true;
    try {
      // Se for admin, garante nomes reais dos usuários antes de renderizar os chamados
      const ru = await api('GET', '/usuarios');
      if (ru.ok && Array.isArray(ru.data)) {
        for (const u of ru.data) {
          const ex = DB.user(u.id);
          if (!ex) {
            DB.s.usuarios.push({
              id: u.id, nome: u.nome, login: u.matricula, ident: u.matricula, email: u.email,
              tipo: u.perfil === 'SOLICITANTE' ? 'Discente' : 'Servidor',
              vinculoAtivo: u.vinculo_ativo, acessoAtivo: u.vinculo_ativo,
              perfis: u.perfil === 'ADMIN' ? ['admin', 'gestor', 'solicitante']
                : u.perfil === 'GESTOR' ? ['gestor', 'solicitante']
                : u.perfil === 'EXECUTOR' ? ['executor', 'solicitante'] : ['solicitante'],
              setor: u.setor || ''
            });
          } else {
            ex.nome = u.nome; ex.login = u.matricula; ex.ident = u.matricula;
          }
        }
      }

      const rl = await api('GET', '/chamados?limite=100');
      if (!rl.ok || !Array.isArray(rl.data)) return;

      const mapa = loadMap();
      let mudou = false;

      for (const resumo of rl.data) {
        const proto = resumo.protocolo;
        const rd = await api('GET', '/chamados/' + encodeURIComponent(proto));
        if (!rd.ok || !rd.data) continue;
        const d = rd.data;
        const rh = await api('GET', '/chamados/' + encodeURIComponent(proto) + '/historico');
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
        const convertido = {
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

        mapa[proto] = proto;
        // Remove eventual cópia local temporária com ID antigo que apontava para este protocolo
        const idTemp = Object.keys(mapa).find(k => k !== proto && mapa[k] === proto);
        if (idTemp) {
          const idxTemp = DB.s.chamados.findIndex(x => x.id === idTemp);
          if (idxTemp >= 0) { DB.s.chamados.splice(idxTemp, 1); mudou = true; }
        }

        const idx = DB.s.chamados.findIndex(x => x.id === proto);
        if (idx >= 0) {
          const prevStr = JSON.stringify(DB.s.chamados[idx]);
          if (prevStr !== JSON.stringify(convertido)) {
            DB.s.chamados[idx] = convertido;
            mudou = true;
          }
        } else {
          DB.s.chamados.unshift(convertido);
          mudou = true;
        }
      }

      saveMap(mapa);
      if (mudou) {
        originalSave();
        anterior = snapshot();
        if (window.App && App.render) App.render();
      }
    } catch (err) {
      console.warn('[UNIFAP Bridge sync]', err);
    } finally {
      sincronizando = false;
    }
  }

  async function autenticarSessao(userId) {
    if (!userId || !getToken()) return;
    await detectarModo();
    const rl = await api('GET', '/catalogo/locais');
    if (rl.ok && Array.isArray(rl.data)) catalogoLocais = rl.data;
    const rc = await api('GET', '/catalogo/categorias');
    if (rc.ok && Array.isArray(rc.data)) catalogoCategorias = rc.data;
    await carregarChamadosDoBackend();
  }

  async function sincronizarNovoChamado(c) {
    const mapa = loadMap();
    if (mapa[c.id]) return;
    const cat = DB.cat(c.categoria);
    const titulo = ((cat ? cat.nome : 'Chamado') + ' - ' + DB.localCurto(c.ambiente)).slice(0, 120);
    const desc = c.descricao && c.descricao.length >= 10
      ? c.descricao
      : (c.descricao || '') + ' (detalhamento adicional registrado)';
    const r = await api('POST', '/chamados', {
      titulo: titulo.length >= 5 ? titulo : 'Chamado UNIFAP',
      descricao: desc === titulo ? desc + '.' : desc,
      local_id: localApi(c.ambiente),
      categoria_id: categoriaApi(c.categoria),
      equipamento: null,
      impacta_aulas: !!c.impedeAula,
      pessoas_afetadas: c.impedeAula ? 30 : 5
    });
    if (r.ok && r.data && r.data.protocolo) {
      const protocolo = r.data.protocolo;
      mapa[c.id] = protocolo;
      saveMap(mapa);
      const pendentes = (window.UnifapPendingUploads && window.UnifapPendingUploads[c.id]) || [];
      if (pendentes.length) {
        delete window.UnifapPendingUploads[c.id];
        const tok = getToken();
        for (const item of pendentes) {
          if (item.raw && tok) {
            const fd = new FormData();
            fd.append('arquivo', item.raw, item.name);
            await fetch('/api/v1/chamados/' + encodeURIComponent(protocolo) + '/evidencias', {
              method: 'POST', headers: { Authorization: 'Bearer ' + tok }, body: fd
            });
          } else if (item.driveUrl) {
            await api('POST', '/chamados/' + encodeURIComponent(protocolo) + '/evidencias/google-drive', {
              url: item.driveUrl,
              nome_arquivo: item.name
            });
          }
        }
      }
      if (window.UI && UI.toast) {
        UI.toast('Sincronizado com o backend: ' + protocolo);
      }
      await carregarChamadosDoBackend();
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
        if (!rAt.ok && window.UI && UI.toast) {
          UI.toast((rAt.data && rAt.data.mensagem) || 'Falha ao salvar atribuição no servidor.', 'err');
        } else {
          await carregarChamadosDoBackend();
        }
      } else if (depois.estado === 'atendimento') {
        await api('POST', '/chamados/' + protocolo + '/iniciar');
      } else if (depois.estado === 'resolvido') {
        const sol = depois.historico.slice(antes.historico.length).find(h => h.tipo === 'comentario');
        const texto = sol && sol.texto.length >= 10 ? sol.texto : 'Atendimento concluído pela equipe técnica.';
        await api('POST', '/chamados/' + protocolo + '/resolver', { solucao: texto });
      } else if (depois.estado === 'concluido' && depois.avaliacao) {
        await api('POST', '/chamados/' + protocolo + '/avaliacao', {
          nota: depois.avaliacao.nota,
          comentario: depois.avaliacao.comentario || null
        });
      } else if (depois.estado === 'reencaminhado') {
        await api('POST', '/triagem/' + protocolo + '/reencaminhar', {
          motivo: 'Reencaminhado pela equipe técnica para nova triagem.'
        });
      } else if (depois.estado === 'cancelado') {
        await api('POST', '/chamados/' + protocolo + '/cancelar', {
          motivo: 'Cancelado pelo usuário na interface.'
        });
      }
      return;
    }

    // Novo comentário interno sem mudança de estado
    if (depois.historico.length > antes.historico.length) {
      const novos = depois.historico.slice(antes.historico.length);
      for (const h of novos) {
        if (h.tipo === 'comentario' && h.texto) {
          await api('POST', '/chamados/' + protocolo + '/comentarios', {
            texto: h.texto,
            interno: h.publico === false
          });
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
      try {
        if (prev.sessao !== atual.sessao) {
          await autenticarSessao(atual.sessao);
        }
        const prevById = new Map(prev.chamados.map(c => [c.id, c]));
        for (const c of DB.s.chamados) {
          const antes = prevById.get(c.id);
          if (!antes) {
            await sincronizarNovoChamado(c);
          } else if (antes.estado !== c.estado || antes.historicoLen !== c.historico.length) {
            await sincronizarAlteracao(antes, c);
          }
        }
      } catch (err) {
        console.warn('[UNIFAP Bridge]', err);
      }
    })();
  };

  if (DB.s.sessao && getToken()) {
    autenticarSessao(DB.s.sessao).catch(() => {});
  }
  window.addEventListener('hashchange', () => {
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
