"""Testes do pipeline completo e dos perfis, com verdade conhecida.

O gerador sintético permite verificar o que nenhum vídeo real permitiria sem
anotação manual: se a elevação do joelho for gerada maior, a métrica **tem** de
subir. É isso que estes testes verificam — não a exactidão biomecânica, que só
se valida com vídeo real e treinador.
"""

from __future__ import annotations

import pytest

from analisetecnica import load_profiles
from analisetecnica.core import pipeline, reporting
from analisetecnica.core.pose.synthetic import archery, cycling, running
from analisetecnica.core.profile import available, get
from analisetecnica.core.types import Side, View

load_profiles()


def _corrida(quality: float, com_frontal: bool = True):
    seqs = {View.LATERAL: running(View.LATERAL, quality=quality)}
    if com_frontal:
        seqs[View.FRONTAL] = running(View.FRONTAL, quality=quality)
    return pipeline.run(get("corrida"), seqs, athlete="teste")


def _ciclismo(quality: float):
    perfil = get("ciclismo")
    seqs = {v.kind: cycling(v.kind, quality=quality) for v in perfil.views}
    return pipeline.run(perfil, seqs, athlete="teste", reference=perfil.reference())


def _arco(quality: float):
    return pipeline.run(
        get("arco"), {View.POSTERIOR: archery(View.POSTERIOR, quality=quality)}, athlete="teste"
    )


# --------------------------------------------------------------------------- #
# Execução ponta a ponta
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fabrica", [_corrida, _ciclismo, _arco])
def test_pipeline_corre_e_produz_score(fabrica):
    analise = fabrica(0.8)
    assert analise.score.technical == analise.score.technical  # não é NaN
    assert 0 <= analise.score.technical <= 100
    assert analise.results
    assert reporting.render(analise)


def test_todos_os_perfis_estao_registados():
    ids = {p.id for p in available()}
    assert ids == {"ciclismo", "corrida", "arco", "natacao", "lancamentos"}


def test_vista_obrigatoria_em_falta_e_erro_explicito():
    with pytest.raises(ValueError, match="exige"):
        pipeline.run(get("corrida"), {View.FRONTAL: running(View.FRONTAL)})


# --------------------------------------------------------------------------- #
# Verdade conhecida: a métrica segue o sinal gerado
# --------------------------------------------------------------------------- #


def test_elevacao_do_joelho_sobe_com_a_qualidade():
    """A pergunta directa do treinador: 'está a levantar melhor o joelho?'"""
    baixa = _corrida(0.3).result("knee_lift_height:right")
    alta = _corrida(0.9).result("knee_lift_height:right")
    assert alta.value.mean > baixa.value.mean
    assert alta.score > baixa.score


def test_elevacao_do_joelho_dispensa_calibracao():
    """Métrica adimensional: normalizada pelo comprimento da perna do atleta."""
    spec = get("corrida").metric("knee_lift_height")
    assert spec.requires.value == "none"
    assert spec.min_fps is None


def test_tipo_de_apoio_do_pe_acompanha_o_gerador():
    """Qualidade baixa gera ataque de calcanhar; alta, apoio mais a meio-pé."""
    calcanhar = _corrida(0.1).result("foot_strike_index:right").value.mean
    medio = _corrida(0.95).result("foot_strike_index:right").value.mean
    assert calcanhar < medio


def test_tempo_de_contacto_e_estavel_entre_passadas():
    """Deteção instável parte um apoio em vários e dispara o desvio-padrão."""
    r = _corrida(0.8).result("ground_contact_time:right")
    assert r.value.n >= 4
    assert r.value.sd < 0.1 * r.value.mean


def test_cadencia_em_passos_por_minuto():
    """Passada ≠ passo: a cadência é o dobro das passadas por minuto."""
    r = _corrida(0.8).result("cadence")
    # gerador: passada de 0.72 s → 2 × 60 / 0.72 ≈ 167 passos/min
    assert r.value.mean == pytest.approx(167, rel=0.05)
    assert r.spec.unit == "passos/min"


def test_queda_da_anca_aumenta_com_qualidade_baixa():
    boa = _corrida(0.9).result("pelvic_drop").value.mean
    ma = _corrida(0.2).result("pelvic_drop").value.mean
    assert ma > boa


def test_extensao_do_joelho_no_ciclismo_segue_a_altura_do_selim():
    baixo = _ciclismo(0.1).result("knee_angle_bdc:right").value.mean
    alto = _ciclismo(0.95).result("knee_angle_bdc:right").value.mean
    assert alto > baixo  # selim mais alto → joelho mais estendido em baixo


def test_repetibilidade_do_arco_distingue_niveis():
    consistente = _arco(0.95).result("anchor_consistency")
    inconsistente = _arco(0.2).result("anchor_consistency")
    assert consistente.score > inconsistente.score


def test_arco_nao_avalia_simetria():
    """A postura do recurvo é deliberadamente assimétrica."""
    assert all(not m.bilateral for m in get("arco").metrics)


# --------------------------------------------------------------------------- #
# Score técnico, score de evolução e confiança
# --------------------------------------------------------------------------- #


def test_score_de_evolucao_e_independente_do_tecnico():
    """Um atleta pode melhorar muito e continuar longe da referência."""
    base = _corrida(0.15)
    atual = pipeline.run(
        get("corrida"),
        {
            View.LATERAL: running(View.LATERAL, quality=0.45),
            View.FRONTAL: running(View.FRONTAL, quality=0.45),
        },
        athlete="teste",
        baseline=base,
    )
    assert atual.progress is not None
    assert atual.progress.mean_delta > 0        # evoluiu
    assert atual.score.technical < 90           # e continua com margem
    assert atual.progress.improved


def test_score_parcial_e_assinalado():
    """Sem a vista frontal, parte do peso do perfil fica por avaliar."""
    analise = _corrida(0.8, com_frontal=False)
    assert analise.score.is_partial
    assert analise.score.covered_weight < analise.score.total_weight
    assert "SCORE PARCIAL" in reporting.render(analise)


def test_score_apresentado_em_bandas_de_cinco_pontos():
    banda = _corrida(0.8).score.banded
    inicio, fim = (int(x) for x in banda.split("–"))
    assert fim - inicio == 5
    assert inicio % 5 == 0


def test_confianca_reflecte_fps_e_calibracao():
    analise = _corrida(0.8)
    c = analise.score.confidence
    assert c.effective_fps == 240.0
    assert c.has_calibration is False
    assert c.repetitions >= 4
    assert c.level in ("alta", "média", "baixa")


def test_metricas_registam_a_versao_da_definicao():
    """Sem versão, o histórico deixa de ser comparável após afinar uma fórmula."""
    for r in _corrida(0.8).results:
        assert r.value.definition_version


def test_metricas_sem_dados_nao_entram_no_score():
    analise = _corrida(0.8, com_frontal=False)
    excluidas = {e.split(" ")[0] for e in analise.score.excluded}
    assert "pelvic_drop" in excluidas
    assert all(r.usable for r in analise.results if r.spec.id == "trunk_lean")


def test_recomendacao_vem_da_propria_metrica():
    analise = _corrida(0.1)
    com_recomendacao = [r for r in analise.results if r.recommendation]
    assert com_recomendacao
    for r in com_recomendacao:
        assert r.recommendation in [x.text for x in r.spec.recommendations]


# --------------------------------------------------------------------------- #
# Perfis sem gerador sintético
# --------------------------------------------------------------------------- #


def _relabel(seq, view: View):
    seq.view = view
    return seq


@pytest.mark.parametrize(
    "perfil_id, vistas",
    [
        ("natacao", {View.INFERIOR: View.LATERAL, View.LATERAL: View.LATERAL}),
        ("lancamentos", {View.LATERAL: View.LATERAL}),
    ],
)
def test_perfis_sem_gerador_executam_sem_rebentar(perfil_id, vistas):
    """Fumo apenas: confirma que os caminhos de código correm.

    Os valores não têm significado biomecânico — a natação e os lançamentos
    não têm gerador sintético, e aqui reutiliza-se cinemática de corrida só
    para exercitar segmentação, métricas e relatório.
    """
    perfil = get(perfil_id)
    seqs = {
        destino: _relabel(running(origem, quality=0.7, n_cycles=4), destino)
        for destino, origem in vistas.items()
    }
    analise = pipeline.run(perfil, seqs, athlete="fumo")
    assert reporting.render(analise)
    assert analise.score.is_partial  # faltam vistas e tracking de objectos
