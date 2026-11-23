from fastapi import APIRouter, Request, Response, status

from src.core.container import ContainerDep
from src.core.exceptions import NaoAutenticado, log_seguranca
from src.core.security import criar_token
from src.modules.autenticacao.dependencies import (
    Admin,
    SessaoAtual,
    UsuarioAtivoParaTroca,
    UsuarioParaTroca,
)
from src.modules.autenticacao.schemas import (
    AlterarPropriaSenhaRequest,
    ConfirmarRedefinicaoSenhaRequest,
    CriarUsuarioRequest,
    EsqueciSenhaRequest,
    LoginRequest,
    MensagemResponse,
    RedefinirSenhaAdminRequest,
    TokenResponse,
    UsuarioAutenticado,
)
from src.modules.autenticacao.service import SENHA_PADRAO_SEED

router = APIRouter(tags=["autenticação e usuários"])


def _ip_cliente(request: Request, confiar_proxy: bool) -> str:
    """V24: lê X-Forwarded-For somente quando atrás de proxy reverso confiável."""
    if confiar_proxy:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip() or "desconhecido"
    return request.client.host if request.client else "desconhecido"


@router.post("/api/v1/auth/login", response_model=TokenResponse)
def login(dados: LoginRequest, request: Request, container: ContainerDep) -> TokenResponse:
    s = container.settings
    ip = _ip_cliente(request, s.confiar_proxy_headers)
    chave_conta, chave_ip = f"conta:{dados.matricula}", f"ip:{ip}"
    limitador = container.limitador_login
    limitador.verificar(chave_conta, s.login_max_tentativas_conta)
    limitador.verificar(chave_ip, s.login_max_tentativas_ip)
    try:
        usuario = container.autenticador.autenticar(dados.matricula, dados.senha)
    except NaoAutenticado:
        limitador.registrar_falha(chave_conta)
        limitador.registrar_falha(chave_ip)
        log_seguranca.warning("LOGIN_FALHOU matricula=%s ip=%s", dados.matricula, ip)
        raise
    limitador.limpar(chave_conta)
    return TokenResponse(
        access_token=criar_token(usuario.id, usuario.perfil.value, s),
        expira_em_segundos=s.jwt_expire_minutes * 60,
        perfil=usuario.perfil,
        deve_redefinir_senha=usuario.deve_redefinir_senha,
        usando_senha_padrao=(dados.senha == SENHA_PADRAO_SEED),
    )


@router.post("/api/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(sessao: SessaoAtual, container: ContainerDep) -> Response:
    container.revogacao.revogar(sessao.jti, sessao.expira_em)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/v1/auth/me", response_model=UsuarioAutenticado)
def me(usuario: UsuarioParaTroca) -> UsuarioAutenticado:
    return usuario


@router.post("/api/v1/auth/alterar-senha", status_code=status.HTTP_204_NO_CONTENT)
def alterar_propria_senha(
    dados: AlterarPropriaSenhaRequest, usuario: UsuarioAtivoParaTroca, container: ContainerDep
) -> Response:
    """Autoatendimento: usuário autenticado redefine sua própria senha."""
    container.autenticador.alterar_propria_senha(usuario.id, dados.senha_atual, dados.nova_senha)
    log_seguranca.info("SENHA_ALTERADA_PROPRIA usuario=%s", usuario.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/v1/auth/esqueci-senha", response_model=MensagemResponse)
def esqueci_senha(
    dados: EsqueciSenhaRequest, request: Request, container: ContainerDep
) -> MensagemResponse:
    """Autoatendimento: solicita recuperação de senha sem revelar se o e-mail existe."""
    s = container.settings
    ip = _ip_cliente(request, s.confiar_proxy_headers)
    chave_ip = f"rec_ip:{ip}"
    container.limitador_login.verificar(chave_ip, s.login_max_tentativas_ip)
    container.limitador_login.registrar_falha(chave_ip)
    container.autenticador.solicitar_recuperacao_senha(dados.email)
    return MensagemResponse(
        mensagem="Se o e-mail estiver cadastrado e ativo, enviaremos instruções de redefinição."
    )


@router.post("/api/v1/auth/redefinir-senha", status_code=status.HTTP_204_NO_CONTENT)
def confirmar_redefinicao_senha(
    dados: ConfirmarRedefinicaoSenhaRequest, request: Request, container: ContainerDep
) -> Response:
    """Autoatendimento: confirma redefinição com token temporário de uso único."""
    s = container.settings
    ip = _ip_cliente(request, s.confiar_proxy_headers)
    chave_ip = f"rec_conf_ip:{ip}"
    container.limitador_login.verificar(chave_ip, s.login_max_tentativas_ip)
    container.limitador_login.registrar_falha(chave_ip)
    container.autenticador.confirmar_recuperacao_senha(dados.token, dados.nova_senha)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ Gestão de Usuários (ADMIN)
@router.post(
    "/api/v1/usuarios",
    response_model=UsuarioAutenticado,
    status_code=status.HTTP_201_CREATED,
)
def criar_usuario(
    dados: CriarUsuarioRequest, admin: Admin, container: ContainerDep
) -> UsuarioAutenticado:
    criado = container.autenticador.criar_usuario(dados)
    log_seguranca.info("USUARIO_CRIADO admin=%s novo=%s perfil=%s",
                       admin.id, criado.id, criado.perfil.value)
    return criado


@router.get("/api/v1/usuarios", response_model=list[UsuarioAutenticado])
def listar_usuarios(_: Admin, container: ContainerDep) -> list[UsuarioAutenticado]:
    return list(container.autenticador.listar_usuarios())


@router.post(
    "/api/v1/usuarios/{usuario_id}/redefinir-senha",
    status_code=status.HTTP_204_NO_CONTENT,
)
def redefinir_senha_admin(
    usuario_id: str,
    dados: RedefinirSenhaAdminRequest,
    admin: Admin,
    container: ContainerDep,
) -> Response:
    """Redefinição manual de senha executada por um administrador."""
    container.autenticador.redefinir_senha(
        usuario_id, dados.nova_senha, deve_redefinir_senha=dados.deve_redefinir_senha
    )
    log_seguranca.info(
        "SENHA_REDEFINIDA_ADMIN admin=%s alvo=%s exigir_troca=%s",
        admin.id, usuario_id, dados.deve_redefinir_senha,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
