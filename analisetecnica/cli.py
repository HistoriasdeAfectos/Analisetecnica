"""Interface de linha de comandos."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import load_profiles
from .core import pipeline, reporting
from .core.pose import io as pose_io
from .core.pose import load as load_backend
from .core.profile import available, get
from .core.types import Calibration, PoseSequence, View

DEMOS = {"ciclismo": "ciclismo", "corrida": "corrida", "arco": "arco"}


def _parse_views(pairs: list[str]) -> dict[View, str]:
    out: dict[View, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(
                f"--vista espera 'vista=ficheiro' (recebido: '{pair}'). "
                f"Vistas: {', '.join(v.value for v in View)}"
            )
        name, path = pair.split("=", 1)
        try:
            out[View(name.strip())] = path.strip()
        except ValueError:
            raise SystemExit(
                f"vista desconhecida '{name}'. Vistas: {', '.join(v.value for v in View)}"
            )
    return out


def cmd_perfis(args: argparse.Namespace) -> int:
    for p in available():
        req = ", ".join(v.value for v in p.required_views())
        opt = ", ".join(v.kind.value for v in p.views if not v.required)
        print(f"{p.id:<14} {p.name:<28} [{p.maturity}]")
        print(f"{'':14} vistas obrigatórias: {req or '—'}")
        if opt:
            print(f"{'':14} vistas opcionais:    {opt}")
        print(f"{'':14} métricas: {len(p.metrics)} · repetições mínimas: {p.min_repetitions}")
        if args.detalhe:
            for m in p.metrics:
                flags = [m.requires.value]
                if m.min_fps:
                    flags.append(f"≥{m.min_fps:.0f}fps")
                if m.bilateral:
                    flags.append("bilateral")
                print(f"{'':16} · {m.id:<28} {m.unit:<12} peso {m.weight:.3f}  ({', '.join(flags)})")
        print()
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    gen = DEMOS.get(args.perfil)
    if gen is None:
        raise SystemExit(
            f"não há gerador sintético para '{args.perfil}'. "
            f"Disponíveis: {', '.join(sorted(DEMOS))}. "
            "Os restantes perfis correm com 'analisar' sobre vídeo real."
        )

    profile = get(args.perfil)
    backend = load_backend("synthetic")

    def build(quality: float) -> dict[View, PoseSequence]:
        seqs = {}
        for spec in profile.views:
            try:
                seqs[spec.kind] = backend.detect(gen, spec.kind, quality=quality)
            except ValueError:
                continue  # o gerador não cobre esta vista
        return seqs

    reference = profile.reference("elite_band")
    current = pipeline.run(
        profile,
        build(args.qualidade),
        athlete=args.atleta or "sessão actual",
        reference=reference,
    )

    baseline = None
    if args.comparar is not None:
        baseline = pipeline.run(
            profile, build(args.comparar), athlete="sessão anterior", reference=reference
        )
        current = pipeline.run(
            profile,
            build(args.qualidade),
            athlete=args.atleta or "sessão actual",
            reference=reference,
            baseline=baseline,
        )

    print(reporting.render(current))
    if args.guardar:
        _save_keypoints(build(args.qualidade), Path(args.guardar))
    return 0


def cmd_analisar(args: argparse.Namespace) -> int:
    profile = get(args.perfil)
    sources = _parse_views(args.vista)
    calibration = (
        Calibration(args.calibracao, "objecto de referência") if args.calibracao else None
    )

    seqs: dict[View, PoseSequence] = {}
    for view, path in sources.items():
        if path.endswith(".json"):
            seq = pose_io.load(path)
            seq.view = view
        else:
            backend = load_backend(args.backend)
            seq = backend.detect(path, view, max_frames=args.max_frames)
        if args.evento:
            seq.tagged_event = args.evento
        if calibration:
            seq.calibration = calibration
        seqs[view] = seq

    baseline_analysis = None
    if args.baseline:
        base_seqs = {}
        for pair in args.baseline:
            view, path = pair.split("=", 1)
            base_seqs[View(view)] = pose_io.load(path)
        baseline_analysis = pipeline.run(
            profile, base_seqs, athlete="baseline", reference=profile.reference("elite_band")
        )

    analysis = pipeline.run(
        profile,
        seqs,
        athlete=args.atleta,
        calibration=calibration,
        reference=profile.reference("elite_band"),
        baseline=baseline_analysis,
    )
    print(reporting.render(analysis))

    if args.guardar:
        _save_keypoints(seqs, Path(args.guardar))
    return 0


def cmd_keypoints(args: argparse.Namespace) -> int:
    """Extrai e guarda keypoints sem calcular métricas."""
    backend = load_backend(args.backend)
    sources = _parse_views(args.vista)
    seqs = {v: backend.detect(p, v, max_frames=args.max_frames) for v, p in sources.items()}
    _save_keypoints(seqs, Path(args.destino))
    return 0


def _save_keypoints(seqs: dict[View, PoseSequence], destino: Path) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    for view, seq in seqs.items():
        path = pose_io.save(seq, destino / f"{view.value}.json")
        print(f"keypoints guardados: {path} ({len(seq.frames)} frames)", file=sys.stderr)
    print(
        "Manter estes ficheiros: as fórmulas das métricas vão mudar e sem os "
        "keypoints o histórico deixa de ser recalculável.",
        file=sys.stderr,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="analisetecnica",
        description="Análise técnica corporal a partir de vídeo e fotografia.",
    )
    sub = p.add_subparsers(dest="comando", required=True)

    sp = sub.add_parser("perfis", help="lista os perfis de desporto registados")
    sp.add_argument("--detalhe", action="store_true", help="mostra as métricas de cada perfil")
    sp.set_defaults(func=cmd_perfis)

    sd = sub.add_parser("demo", help="corre o pipeline com dados sintéticos, sem vídeo")
    sd.add_argument("--perfil", default="ciclismo", choices=sorted(DEMOS))
    sd.add_argument("--qualidade", type=float, default=0.8,
                    help="qualidade técnica simulada, 0–1 (omissão: 0.8)")
    sd.add_argument("--comparar", type=float, default=None, metavar="QUALIDADE",
                    help="gera também uma sessão anterior com esta qualidade e mostra a evolução")
    sd.add_argument("--atleta", default="")
    sd.add_argument("--guardar", metavar="DIR", help="guarda os keypoints gerados")
    sd.set_defaults(func=cmd_demo)

    sa = sub.add_parser("analisar", help="analisa vídeo real ou keypoints guardados")
    sa.add_argument("--perfil", required=True)
    sa.add_argument("--vista", action="append", required=True, metavar="VISTA=FICHEIRO",
                    help="ex.: --vista lateral=corrida.mov (aceita .json de keypoints)")
    sa.add_argument("--atleta", default="")
    sa.add_argument("--backend", default="mediapipe")
    sa.add_argument("--evento", help="obrigatório em modo fotografia: que instante a imagem representa")
    sa.add_argument("--calibracao", type=float, metavar="PX_POR_METRO")
    sa.add_argument("--baseline", action="append", metavar="VISTA=FICHEIRO.json",
                    help="sessão anterior, para o score de evolução")
    sa.add_argument("--max-frames", type=int, default=None)
    sa.add_argument("--guardar", metavar="DIR", help="guarda os keypoints extraídos")
    sa.set_defaults(func=cmd_analisar)

    sk = sub.add_parser("keypoints", help="extrai keypoints de vídeo e guarda em JSON")
    sk.add_argument("--vista", action="append", required=True, metavar="VISTA=FICHEIRO")
    sk.add_argument("--destino", required=True)
    sk.add_argument("--backend", default="mediapipe")
    sk.add_argument("--max-frames", type=int, default=None)
    sk.set_defaults(func=cmd_keypoints)

    return p


def main(argv: list[str] | None = None) -> int:
    load_profiles()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (KeyError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
