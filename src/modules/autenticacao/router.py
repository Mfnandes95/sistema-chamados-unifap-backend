from fastapi import APIRouter, Request, Response, status

from src.core.container import ContainerDep
from src.core.exceptions import NaoAutenticado, log_seguranca
from src.core.security import criar_token
from src.modules.autenticacao.dependencies import SessaoAtual, UsuarioAtual
from src.modules.autenticacao.schemas import LoginRequest, TokenResponse, UsuarioAutenticado

router = APIRouter(prefix="/api/v1/auth", tags=["autenticação"])


@router.post("/login", response_model=TokenResponse)
def login(dados: LoginRequest, request: Request, container: ContainerDep) -> TokenResponse:
    s = container.settings
    ip = request.client.host if request.client else "desconhecido"
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
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(sessao: SessaoAtual, container: ContainerDep) -> Response:
    container.revogacao.revogar(sessao.jti, sessao.expira_em)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UsuarioAutenticado)
def me(usuario: UsuarioAtual) -> UsuarioAutenticado:
    return usuario
