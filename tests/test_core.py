"""Testes do núcleo: geometria, lateralidade, filtragem, segmentação, alvos."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from analisetecnica.core import filtering
from analisetecnica.core.geometry import angle, angle_to_horizontal, two_link_ik
from analisetecnica.core.keypoints import resolve
from analisetecnica.core.metrics import (
    BandTarget,
    ConsistencyTarget,
    MatchReferenceTarget,
    MinimizeTarget,
)
from analisetecnica.core.pose import io as pose_io
from analisetecnica.core.pose.synthetic import cycling, running
from analisetecnica.core.scoring import classify
from analisetecnica.core.segmentation import InstantSegmenter, dominant_period
from analisetecnica.core.types import (
    Band,
    Laterality,
    Point,
    PoseFrame,
    PoseSequence,
    Side,
    View,
)


# --------------------------------------------------------------------------- #
# Geometria
# --------------------------------------------------------------------------- #


def test_angle_reto():
    a, b, c = Point(0, 1), Point(0, 0), Point(1, 0)
    assert angle(a, b, c) == pytest.approx(90.0)


def test_angle_estendido():
    a, b, c = Point(-1, 0), Point(0, 0), Point(1, 0)
    assert angle(a, b, c) == pytest.approx(180.0)


def test_height_cresce_para_cima():
    """`y` de imagem cresce para baixo; `height` tem de inverter isso."""
    alto, baixo = Point(0, 0.2), Point(0, 0.8)
    assert alto.height > baixo.height


def test_angle_to_horizontal_sinal():
    # b acima de a (y menor) → ângulo positivo
    assert angle_to_horizontal(Point(0, 0.5), Point(0.1, 0.4)) > 0


def test_two_link_ik_respeita_comprimentos():
    root, end = Point(0.0, 0.0), Point(0.0, 0.25)
    knee = two_link_ik(root, end, 0.15, 0.17)
    assert math.dist((root.x, root.y), (knee.x, knee.y)) == pytest.approx(0.15, abs=1e-6)
    assert math.dist((end.x, end.y), (knee.x, knee.y)) == pytest.approx(0.17, abs=1e-6)


# --------------------------------------------------------------------------- #
# Lateralidade — a armadilha que inverte silenciosamente toda a simetria
# --------------------------------------------------------------------------- #


def test_lateralidade_directa():
    assert resolve("knee", Side.LEFT, Laterality.DIRECT) == "left_knee"


def test_lateralidade_espelhada_troca_os_lados():
    assert resolve("knee", Side.LEFT, Laterality.MIRRORED) == "right_knee"
    assert resolve("knee", Side.RIGHT, Laterality.MIRRORED) == "left_knee"


def test_lateralidade_sem_lado_nao_prefixa():
    assert resolve("nose", None, Laterality.MIRRORED) == "nose"


# --------------------------------------------------------------------------- #
# Filtragem
# --------------------------------------------------------------------------- #


def _ruidosa(n=200, fps=100.0, sigma=0.01, seed=0) -> PoseSequence:
    rng = np.random.default_rng(seed)
    t = np.arange(n) / fps
    base = 0.5 + 0.1 * np.sin(2 * math.pi * 1.5 * t)
    frames = [
        PoseFrame(i, {"right_knee": Point(0.5, float(base[i] + rng.normal(0, sigma)), 0.9)})
        for i in range(n)
    ]
    return PoseSequence(frames=frames, view=View.LATERAL, fps=fps)


def test_filtragem_reduz_ruido():
    seq = _ruidosa()
    filtrada, report = filtering.apply(seq, filtering.FilterSpec(cutoff_hz=6.0))
    assert report.smoothing_applied

    def rugosidade(s: PoseSequence) -> float:
        ys = [f.keypoints["right_knee"].y for f in s.frames]
        return sum(abs(ys[i + 1] - 2 * ys[i] + ys[i - 1]) for i in range(1, len(ys) - 1))

    assert rugosidade(filtrada) < rugosidade(seq) / 3


def test_filtragem_nao_altera_a_sequencia_original():
    """As métricas de tremor dependem do sinal cru continuar disponível."""
    seq = _ruidosa()
    antes = [f.keypoints["right_knee"].y for f in seq.frames]
    filtering.apply(seq, filtering.FilterSpec())
    assert [f.keypoints["right_knee"].y for f in seq.frames] == antes


def test_filtragem_recusa_corte_acima_de_nyquist():
    seq = _ruidosa(fps=10.0)
    _, report = filtering.apply(seq, filtering.FilterSpec(cutoff_hz=8.0))
    assert not report.smoothing_applied
    assert "Nyquist" in report.smoothing_skipped_reason


def test_filtragem_descarta_baixa_confianca():
    seq = _ruidosa(n=40)
    seq.frames[10].keypoints["right_knee"] = Point(0.5, 0.5, 0.1)
    _, report = filtering.apply(seq, filtering.FilterSpec(confidence_threshold=0.5))
    assert report.dropped_by_confidence >= 1


# --------------------------------------------------------------------------- #
# Segmentação
# --------------------------------------------------------------------------- #


def test_periodo_dominante():
    n, period = 400, 40
    sig = np.sin(2 * math.pi * np.arange(n) / period)
    assert dominant_period(sig) == pytest.approx(period, rel=0.05)


def test_modo_fotografia_exige_evento_etiquetado():
    seq = PoseSequence(frames=[PoseFrame(0, {"nose": Point(0.5, 0.5)})], view=View.LATERAL)
    with pytest.raises(ValueError, match="tagged_event"):
        InstantSegmenter().segment(seq)


def test_modo_fotografia_recusa_evento_de_outro_perfil():
    seq = PoseSequence(
        frames=[PoseFrame(0, {"nose": Point(0.5, 0.5)})],
        view=View.LATERAL,
        tagged_event="largada",
    )
    with pytest.raises(ValueError, match="não pertence"):
        InstantSegmenter(accepted_events=["peak_knee_lift"]).segment(seq)


# --------------------------------------------------------------------------- #
# Alvos e classificação
# --------------------------------------------------------------------------- #


def test_band_target_pontua_100_dentro_da_faixa():
    assert BandTarget(10.0, 20.0).evaluate(15.0).score == 100.0


def test_band_target_distingue_os_dois_lados():
    alvo = BandTarget(10.0, 20.0, tolerance=10.0)
    assert alvo.evaluate(5.0).direction == "below"
    assert alvo.evaluate(25.0).direction == "above"


def test_band_target_nao_e_monotono():
    """Inclinação do tronco: 0° e 20° são ambos defeitos, 8° não."""
    alvo = BandTarget(4.0, 12.0, tolerance=8.0)
    assert alvo.evaluate(8.0).score > alvo.evaluate(0.0).score
    assert alvo.evaluate(8.0).score > alvo.evaluate(20.0).score


def test_match_reference_usa_desvios_padrao_nao_percentagem():
    """Sobre valores perto de zero, a diferença percentual explodiria."""
    banda = Band(mean=0.001, sd=0.02, samples=8)
    alvo = MatchReferenceTarget()
    resultado = alvo.evaluate(0.011, banda)
    assert resultado.score > 80  # meio desvio-padrão é um desvio pequeno
    assert math.isfinite(resultado.deviation)


def test_consistency_base_sd_para_valores_perto_de_zero():
    """Com média ≈ 0 o coeficiente de variação dispara; o desvio-padrão não."""
    alvo_cv = ConsistencyTarget(basis="cv")
    alvo_sd = ConsistencyTarget(good_cv=0.02, bad_cv=0.12, basis="sd")
    media, sd = 0.001, 0.01
    cv = abs(sd / media)
    assert alvo_cv.dispersion(media, sd, cv) > 1.0
    assert alvo_sd.dispersion(media, sd, cv) == sd


def test_minimize_target_satura():
    alvo = MinimizeTarget(0.05, 0.25)
    assert alvo.evaluate(0.01).score == 100.0
    assert alvo.evaluate(0.40).score == 0.0


def test_classificacao_por_fraccao_do_intervalo():
    assert classify(0.02) == "verde"
    assert classify(0.10) == "amarelo"
    assert classify(0.40) == "vermelho"
    assert classify(float("nan")) == "indeterminado"


# --------------------------------------------------------------------------- #
# Persistência dos keypoints em bruto
# --------------------------------------------------------------------------- #


def test_keypoints_sobrevivem_a_ida_e_volta(tmp_path: Path):
    seq = running(View.LATERAL, n_cycles=1, quality=0.7)
    caminho = pose_io.save(seq, tmp_path / "lateral.json")
    lida = pose_io.load(caminho)

    assert len(lida.frames) == len(seq.frames)
    assert lida.fps == seq.fps
    assert lida.view is seq.view
    original = seq.frames[5].keypoints["right_knee"]
    recuperado = lida.frames[5].keypoints["right_knee"]
    assert recuperado.x == pytest.approx(original.x, abs=1e-6)
    assert recuperado.y == pytest.approx(original.y, abs=1e-6)


def test_formato_futuro_e_recusado(tmp_path: Path):
    seq = cycling(View.LATERAL, n_cycles=1)
    dados = pose_io.to_dict(seq)
    dados["format_version"] = 99
    with pytest.raises(ValueError, match="formato"):
        pose_io.from_dict(dados)
