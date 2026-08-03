"""Testes das invariantes de arquitectura.

Estas regras são o que impede a base de se tornar específica de um desporto.
São verificáveis automaticamente, por isso são testadas — não deixadas a
disciplina de revisão.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from analisetecnica import load_profiles
from analisetecnica.core.metrics import ConsistencyTarget
from analisetecnica.core.profile import available
from analisetecnica.core.types import Requires

load_profiles()

CORE = Path(__file__).resolve().parent.parent / "analisetecnica" / "core"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.append("." * node.level + (node.module or ""))
    return out


@pytest.mark.parametrize("ficheiro", sorted(CORE.rglob("*.py")), ids=lambda p: p.name)
def test_core_nao_importa_de_sports(ficheiro: Path):
    """Se for preciso importar um desporto no núcleo, falta uma abstracção."""
    for nome in _imports(ficheiro):
        assert "sports" not in nome, f"{ficheiro.name} importa '{nome}'"


@pytest.mark.parametrize("perfil", available(), ids=lambda p: p.id)
def test_perfil_tem_pelo_menos_uma_vista_obrigatoria(perfil):
    assert perfil.required_views()


@pytest.mark.parametrize("perfil", available(), ids=lambda p: p.id)
def test_pesos_dos_grupos_somam_um(perfil):
    if not perfil.group_weights:
        pytest.skip("perfil sem pesos por grupo")
    assert sum(perfil.group_weights.values()) == pytest.approx(1.0)
    assert sum(m.weight for m in perfil.metrics) == pytest.approx(1.0)


@pytest.mark.parametrize("perfil", available(), ids=lambda p: p.id)
def test_metricas_declaram_o_que_exigem(perfil):
    for m in perfil.metrics:
        assert isinstance(m.requires, Requires)
        # Uma métrica temporal sem cadência mínima declarada seria avaliada
        # em vídeo de 30 fps sem qualquer aviso.
        if m.requires is Requires.FPS:
            assert m.min_fps, f"{perfil.id}/{m.id} exige fps mas não declara mínimo"


@pytest.mark.parametrize("perfil", available(), ids=lambda p: p.id)
def test_metricas_usam_apenas_vistas_declaradas_no_perfil(perfil):
    declaradas = {v.kind for v in perfil.views}
    for m in perfil.metrics:
        assert set(m.views) <= declaradas, f"{perfil.id}/{m.id}"


@pytest.mark.parametrize("perfil", available(), ids=lambda p: p.id)
def test_identificadores_de_metrica_sao_unicos(perfil):
    ids = [m.id for m in perfil.metrics]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("perfil", available(), ids=lambda p: p.id)
def test_referencias_sao_bandas_e_assinalam_n_igual_a_um(perfil):
    for ref in perfil.references:
        for chave, banda in ref.bands.items():
            assert banda.sd > 0, f"{perfil.id}/{chave}: banda sem dispersão"
            assert banda.is_weak == (banda.samples <= 1)


@pytest.mark.parametrize("perfil", available(), ids=lambda p: p.id)
def test_metricas_de_repetibilidade_exigem_repeticoes(perfil):
    tem_consistencia = any(isinstance(m.target, ConsistencyTarget) for m in perfil.metrics)
    if tem_consistencia:
        assert perfil.min_repetitions >= 2


@pytest.mark.parametrize("perfil", available(), ids=lambda p: p.id)
def test_metricas_com_ressalva_declaram_texto(perfil):
    for m in perfil.metrics:
        if m.uses_raw_signal:
            assert m.caveat, f"{perfil.id}/{m.id}: usa sinal cru sem explicar porquê"


@pytest.mark.parametrize("perfil", available(), ids=lambda p: p.id)
def test_perfil_documenta_riscos(perfil):
    assert perfil.risks, f"{perfil.id} não declara riscos conhecidos"


def test_vistas_posterior_e_inferior_sao_espelhadas():
    """O eixo esquerda/direita inverte-se; trocar isto inverte a simetria."""
    from analisetecnica.core.types import Laterality, View

    for perfil in available():
        for v in perfil.views:
            if v.kind in (View.POSTERIOR, View.INFERIOR):
                assert v.laterality is Laterality.MIRRORED, f"{perfil.id}/{v.kind.value}"
