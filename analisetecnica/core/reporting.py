"""Relatório em texto. Todo o texto técnico vem das próprias `MetricSpec`."""

from __future__ import annotations

from .metrics import ConsistencyTarget
from .pipeline import Analysis
from .scoring import MetricResult

MARK = {"verde": "OK ", "amarelo": " ! ", "vermelho": " X ", "indeterminado": " ? "}


def _fmt(v: float, unit: str) -> str:
    if v != v:
        return "—"
    if unit in ("ratio", "cv"):
        return f"{v:+.3f}" if unit == "ratio" else f"{v:.3f}"
    return f"{v:.1f} {unit}" if unit else f"{v:.1f}"


def _metric_line(r: MetricResult) -> str:
    lado = f" [{r.value.side.value[0].upper()}]" if r.value.side else ""
    nome = f"{r.spec.name}{lado}"
    if not r.value.validity.is_usable:
        return f"  {MARK['indeterminado']} {nome:<44} não avaliada — {r.value.validity.value}"

    if isinstance(r.spec.target, ConsistencyTarget):
        # Nestas métricas o que é pontuado é a dispersão entre repetições, não
        # a média — mostrar a média daria a impressão errada do que falhou.
        dispersion = r.spec.target.dispersion(r.value.mean, r.value.sd, r.value.cv)
        valor = f"{dispersion:.3f} {r.spec.target.basis}"
    else:
        valor = _fmt(r.value.mean, r.spec.unit)
        if r.value.n > 1:
            valor += f" ±{r.value.sd:.3f}" if r.spec.unit in ("ratio", "cv") else f" ±{r.value.sd:.1f}"
    score = "—" if r.score != r.score else f"{r.score:4.0f}"
    return f"  {MARK[r.classification]} {nome:<44} {valor:>16}   score {score}  (n={r.value.n})"


def render(analysis: Analysis) -> str:
    p = analysis.profile
    s = analysis.score
    out: list[str] = []

    out.append("=" * 78)
    title = f"ANÁLISE TÉCNICA — {p.name}"
    if analysis.athlete:
        title += f" — {analysis.athlete}"
    out.append(title)
    out.append("=" * 78)

    # -- score ---------------------------------------------------------------
    out.append("")
    out.append("SCORE TÉCNICO")
    if s.technical != s.technical:
        out.append("  Indeterminado — nenhuma métrica avaliável.")
    else:
        out.append(f"  {s.banded} (banda de 5 pontos)     confiança: {s.confidence.level}")
    c = s.confidence
    out.append(
        f"  pose {c.pose_confidence:.2f} · fps {c.effective_fps or '—'} · "
        f"calibração {'sim' if c.has_calibration else 'não'} · repetições {c.repetitions}"
    )
    if s.is_partial:
        pct = 100 * s.covered_weight / s.total_weight if s.total_weight else 0
        out.append(
            f"  SCORE PARCIAL — {pct:.0f}% do peso do perfil foi avaliado. "
            "Não comparável com um score completo."
        )

    if s.by_group:
        out.append("")
        out.append("  Por grupo:")
        for g, v in sorted(s.by_group.items(), key=lambda kv: -kv[1]):
            barra = "█" * int(round(v / 5))
            out.append(f"    {g:<28} {v:5.1f}  {barra}")

    # -- evolução ------------------------------------------------------------
    if analysis.progress and analysis.progress.entries:
        pr = analysis.progress
        out.append("")
        out.append("SCORE DE EVOLUÇÃO")
        out.append(
            "  (independente do score técnico — melhorar muito e continuar em 60 "
            "são factos compatíveis)"
        )
        out.append(f"  Variação média: {pr.mean_delta:+.1f} pontos face a {pr.baseline_label or 'baseline'}")
        for e in pr.improved[:5]:
            out.append(f"    ↑ {e.metric_id:<40} {e.baseline:5.0f} → {e.current:5.0f}  ({e.delta:+.0f})")
        for e in pr.regressed[:5]:
            out.append(f"    ↓ {e.metric_id:<40} {e.baseline:5.0f} → {e.current:5.0f}  ({e.delta:+.0f})")

    # -- métricas ------------------------------------------------------------
    out.append("")
    out.append("MÉTRICAS")
    grupos: dict[str, list[MetricResult]] = {}
    for r in analysis.results:
        grupos.setdefault(r.spec.group, []).append(r)
    for grupo, rs in grupos.items():
        out.append("")
        out.append(f"  {grupo.upper()}")
        for r in rs:
            out.append(_metric_line(r))

    # -- pontos fortes e a melhorar -----------------------------------------
    fortes = [r for r in analysis.results if r.usable and r.classification == "verde"]
    fracos = [
        r for r in analysis.results if r.usable and r.classification in ("amarelo", "vermelho")
    ]
    fracos.sort(key=lambda r: r.score)

    if fortes:
        out.append("")
        out.append("PONTOS FORTES")
        for r in fortes[:6]:
            lado = f" [{r.value.side.value}]" if r.value.side else ""
            out.append(f"  · {r.spec.name}{lado}")

    if fracos:
        out.append("")
        out.append("A MELHORAR")
        for r in fracos[:8]:
            lado = f" [{r.value.side.value}]" if r.value.side else ""
            out.append(f"  · {r.spec.name}{lado} — {r.classification}")
            rec = r.recommendation
            if rec:
                out.append(f"      → {rec}")
            if r.spec.caveat:
                out.append(f"      ⚠ {r.spec.caveat}")

    # -- ressalvas -----------------------------------------------------------
    excl = s.excluded
    if excl:
        out.append("")
        out.append("NÃO AVALIADO")
        for e in excl[:12]:
            out.append(f"  · {e}")
        if len(excl) > 12:
            out.append(f"  · (+{len(excl) - 12})")

    if analysis.warnings:
        out.append("")
        out.append("AVISOS")
        for w in analysis.warnings:
            out.append(f"  · {w}")

    if p.risks:
        out.append("")
        out.append("RISCOS CONHECIDOS DESTE PERFIL")
        for r in p.risks:
            out.append(f"  · {r}")

    out.append("")
    out.append("-" * 78)
    out.append(
        f"perfil {p.id} ({p.maturity}) · os limites de banda e pesos são pontos de "
        "partida a validar com treinadores"
    )
    return "\n".join(out)
