/* Dados simulados — nada aqui sai do navegador.
   O estado vive em memória e é guardado no sessionStorage para sobreviver a um recarregamento. */
(function () {
  'use strict';

  const HOJE = new Date('2026-11-18T10:30:00');

  /* ---------- Vocabulário fixo ---------- */
  const ESTADOS = {
    triagem:       { label: 'Aguardando triagem', icon: 'hourglass_top',  tone: 'neutral', step: 0 },
    atribuido:     { label: 'Atribuído',          icon: 'assignment_ind', tone: 'info'   ,   step: 1 },
    reencaminhado: { label: 'Reencaminhado',      icon: 'alt_route',      tone: 'warning', step: 1 },
    atendimento:   { label: 'Em atendimento',     icon: 'construction',   tone: 'info'   ,   step: 2 },
    resolvido:     { label: 'Resolvido',          icon: 'task_alt',       tone: 'success', step: 3 },
    concluido:     { label: 'Concluído',          icon: 'verified',       tone: 'success', step: 4 },
    cancelado:     { label: 'Cancelado',          icon: 'block',          tone: 'danger',  step: -1 }
  };
  const TRILHA = ['triagem', 'atribuido', 'atendimento', 'resolvido', 'concluido'];

  const PRIORIDADES = {
    alta:  { label: 'Alta',  icon: 'keyboard_double_arrow_up', tone: 'danger' },
    media: { label: 'Média', icon: 'drag_handle',              tone: 'warning' },
    baixa: { label: 'Baixa', icon: 'keyboard_arrow_down',      tone: 'neutral' }
  };

  const PERFIS = {
    solicitante: { label: 'Solicitante',            desc: 'Abrir e acompanhar os próprios chamados' },
    gestor:      { label: 'Gestor / triagem',       desc: 'Fila, atribuição e relatórios' },
    executor:    { label: 'Executor',               desc: 'Demandas e registro de atendimento' },
    reitoria:    { label: 'Reitoria (consulta)',    desc: 'Relatórios e exportação, sem alterar chamados' },
    admin:       { label: 'Administrador do sistema', desc: 'Usuários, permissões, locais e categorias' }
  };

  const SETORES = ['Manutenção predial', 'Elétrica', 'Limpeza', 'Refrigeração', 'Tecnologia da informação', 'Administração do campus', 'Reitoria'];
  const TIPOS_AMBIENTE = ['Sala de aula', 'Laboratório', 'Auditório', 'Banheiro', 'Área comum', 'Setor administrativo', 'Depósito'];

  /* ---------- Catálogo ---------- */
  const categorias = [
    { id: 'predial', nome: 'Manutenção predial',       icon: 'construction',      setor: 'Manutenção predial',       ativo: true, exemplo: 'Portas, janelas, forro, pintura, vazamentos' },
    { id: 'eletrica', nome: 'Elétrica',                icon: 'bolt',              setor: 'Elétrica',                 ativo: true, exemplo: 'Tomadas, lâmpadas, disjuntores, fiação' },
    { id: 'refrig', nome: 'Refrigeração',              icon: 'mode_fan',          setor: 'Refrigeração',             ativo: true, exemplo: 'Ar-condicionado, bebedouros, ventiladores' },
    { id: 'ti', nome: 'Tecnologia da informação',      icon: 'lan',               setor: 'Tecnologia da informação', ativo: true, exemplo: 'Rede, projetores, computadores de sala' },
    { id: 'limpeza', nome: 'Limpeza',                  icon: 'cleaning_services', setor: 'Limpeza',                  ativo: true, exemplo: 'Sujeira acumulada, lixo, banheiros' },
    { id: 'jardim', nome: 'Jardinagem',                icon: 'yard',              setor: 'Manutenção predial',       ativo: false, exemplo: 'Poda e áreas verdes' }
  ];

  const campi = [
    { id: 'mz',  nome: 'Marco Zero do Equador', codigo: 'MZ',  ativo: true },
    { id: 'bin', nome: 'Binacional (Oiapoque)', codigo: 'BIN', ativo: true },
    { id: 'maz', nome: 'Mazagão',               codigo: 'MAZ', ativo: true },
    { id: 'san', nome: 'Santana',               codigo: 'SAN', ativo: true }
  ];
  const blocos = [];
  const andares = [];
  const ambientes = [];

  const NOMES_ANDAR = ['Térreo', '1º andar', '2º andar'];
  function addBloco(campus, letra, nome, nAndares, ativo) {
    const bid = campus + '-' + letra.toLowerCase();
    blocos.push({ id: bid, campus, nome, codigo: letra, ativo });
    for (let a = 0; a < nAndares; a++) {
      const aid = bid + '-' + a;
      andares.push({ id: aid, bloco: bid, nome: NOMES_ANDAR[a], ativo: true });
      [1, 2, 3, 5].forEach((n, i) => {
        const s = i + 1;
        const codigo = letra + '-' + (a === 0 ? 'T' : a) + '0' + n;
        ambientes.push({ id: aid + '-' + s, andar: aid, nome: 'Sala ' + codigo, codigo, tipo: 'Sala de aula', ativo: true });
      });
    }
  }
  addBloco('mz', 'A', 'Bloco A', 3, true);
  addBloco('mz', 'B', 'Bloco B', 3, true);
  addBloco('mz', 'C', 'Bloco C', 2, true);
  addBloco('mz', 'D', 'Bloco D', 2, true);
  addBloco('mz', 'F', 'Bloco F', 1, false);
  addBloco('bin', 'P', 'Bloco principal', 2, true);
  addBloco('maz', 'P', 'Bloco principal', 1, true);
  addBloco('san', 'P', 'Bloco principal', 2, true);

  // Ambientes nomeados que aparecem nos chamados
  ambientes.push(
    { id: 'mz-b-2-x1', andar: 'mz-b-2', nome: 'Sala B-204', codigo: 'B-204', tipo: 'Sala de aula', ativo: true },
    { id: 'mz-b-2-x2', andar: 'mz-b-2', nome: 'Depósito B-2', codigo: 'B-2D', tipo: 'Depósito', ativo: false },
    { id: 'mz-b-1-x1', andar: 'mz-b-1', nome: 'Banheiro feminino B-1', codigo: 'B-1BF', tipo: 'Banheiro', ativo: true },
    { id: 'mz-c-0-x1', andar: 'mz-c-0', nome: 'Laboratório de Química', codigo: 'C-LQ1', tipo: 'Laboratório', ativo: true },
    { id: 'mz-c-1-x1', andar: 'mz-c-1', nome: 'Laboratório de Informática 2', codigo: 'C-LI2', tipo: 'Laboratório', ativo: true },
    { id: 'mz-a-0-x1', andar: 'mz-a-0', nome: 'Auditório Central', codigo: 'A-AUD', tipo: 'Auditório', ativo: true },
    { id: 'mz-d-0-x1', andar: 'mz-d-0', nome: 'Biblioteca Central', codigo: 'D-BIB', tipo: 'Setor administrativo', ativo: true },
    { id: 'mz-d-1-x1', andar: 'mz-d-1', nome: 'Coordenação de Engenharia', codigo: 'D-CEN', tipo: 'Setor administrativo', ativo: true }
  );

  /* ---------- Pessoas (carregadas do backend/Supabase) ---------- */
  const usuarios = [];

  /* ---------- Chamados (carregados do backend/Supabase) ---------- */
  const chamados = [];

  /* ---------- Store ---------- */
  const KEY = 'unifap-chamados-v3';
  const inicial = () => ({
    chamados: [], usuarios: [], categorias, campi, blocos, andares, ambientes,
    seq: 1, sessao: null, auditoria: []
  });

  let state;
  try {
    const raw = sessionStorage.getItem(KEY);
    state = raw ? JSON.parse(raw) : inicial();
  } catch (e) { state = inicial(); }

  const historicoRelatorio = [];

  function save() {
    try { sessionStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* armazenamento indisponível: segue só em memória */ }
  }
  function reset() {
    try { sessionStorage.removeItem(KEY); } catch (e) { /* ok */ }
    state = inicial();
  }

  /* ---------- Consultas ---------- */
  const byId = (list, id) => list.find(x => x.id === id);
  const DB = {
    HOJE, ESTADOS, TRILHA, PRIORIDADES, PERFIS, SETORES, TIPOS_AMBIENTE,
    get s() { return state; },
    save, reset,
    historicoRelatorio,
    user: id => byId(state.usuarios, id),
    cat: id => byId(state.categorias, id),
    chamado: id => byId(state.chamados, id),
    amb: id => byId(state.ambientes, id),
    andar: id => byId(state.andares, id),
    bloco: id => byId(state.blocos, id),
    campus: id => byId(state.campi, id),
    localPartes(ambId) {
      const a = this.amb(ambId); if (!a) return null;
      const an = this.andar(a.andar), b = this.bloco(an.bloco), c = this.campus(b.campus);
      return { campus: c, bloco: b, andar: an, ambiente: a };
    },
    localCurto(ambId) {
      const p = this.localPartes(ambId); if (!p) return '—';
      return p.ambiente.nome + ', ' + p.bloco.nome;
    },
    localCompleto(ambId) {
      const p = this.localPartes(ambId); if (!p) return '—';
      return [p.campus.nome, p.bloco.nome, p.andar.nome, p.ambiente.nome].join(' › ');
    },
    calcPrioridade(catId, impedeAula) {
      if (impedeAula) return 'alta';
      return (catId === 'eletrica' || catId === 'refrig' || catId === 'predial') ? 'media' : 'baixa';
    },
    novoProtocolo() {
      state.seq += 1;
      return '2026-' + String(state.seq).padStart(4, '0');
    },
    can(perm) {
      const u = state.sessao && this.user(state.sessao);
      return !!u && u.perfis.includes(perm);
    }
  };

  window.DB = DB;
})();
