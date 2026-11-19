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

  async function autenticarSessao(userId) {
    if (!userId || !getToken()) return;
    await detectarModo();
    const rl = await api('GET', '/catalogo/locais');
    if (rl.ok && Array.isArray(rl.data)) catalogoLocais = rl.data;
    const rc = await api('GET', '/catalogo/categorias');
    if (rc.ok && Array.isArray(rc.data)) catalogoCategorias = rc.data;
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
      mapa[c.id] = r.data.protocolo;
      saveMap(mapa);
      if (window.UI && UI.toast) {
        UI.toast('Sincronizado com o backend: ' + r.data.protocolo);
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
        await api('POST', '/triagem/' + protocolo + '/atribuir', {
          executor_id: executorIdApi(depois.executor),
          observacao: obsEv ? obsEv.texto : null
        });
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

  if (DB.s.sessao && !getToken()) {
    autenticarSessao(DB.s.sessao).catch(() => {});
  }

  window.UnifapApi = {
    get token() { return getToken(); },
    get protocolos() { return loadMap(); },
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
