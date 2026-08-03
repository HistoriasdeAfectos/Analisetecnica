# Analisetecnica

Software de análise de técnica corporal por vídeo e fotografia, multidesporto.

Compara a execução técnica de um atleta com bandas de referência de elite ou com
o seu próprio histórico, extrai métricas biomecânicas a partir de deteção de pose
e gera relatórios de evolução.

## Experimentar sem vídeo

O pipeline completo corre com dados sintéticos, sem câmara nem modelo de pose:

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"

.venv/bin/analisetecnica perfis                     # perfis disponíveis
.venv/bin/analisetecnica demo --perfil ciclismo     # análise completa
.venv/bin/analisetecnica demo --perfil corrida --qualidade 0.85 --comparar 0.35
.venv/bin/analisetecnica demo --perfil arco
```

A opção `--comparar` gera uma sessão anterior de qualidade mais baixa e mostra o
score de evolução ao lado do score técnico.

> Os dados sintéticos são cinematicamente plausíveis, não medidos. Servem para
> verificar o pipeline e dar aos testes uma verdade conhecida — nunca para
> validar bandas de referência.

## Analisar vídeo real

```bash
.venv/bin/pip install -e ".[pose]"
mkdir -p models && curl -L -o models/pose_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task

.venv/bin/analisetecnica analisar --perfil corrida \
  --vista lateral=lateral.mov --vista frontal=frontal.mov \
  --atleta "Nome" --guardar sessoes/2026-08-03
```

Antes de gravar, ler o [protocolo de captura](docs/CAPTURE.md) — três definições
do telemóvel (estabilização, modo cinema, lente fixa) determinam se os dados são
aproveitáveis.

`--guardar` grava os keypoints em bruto. **Manter esses ficheiros:** as fórmulas
das métricas vão mudar, e sem eles o histórico deixa de ser recalculável. Uma
sessão guardada volta a ser analisada apontando o JSON em vez do vídeo:

```bash
.venv/bin/analisetecnica analisar --perfil corrida --vista lateral=sessoes/2026-08-03/lateral.json
```

## Testes

```bash
.venv/bin/pytest                              # tudo
.venv/bin/pytest tests/test_arquitectura.py   # só as invariantes de arquitectura
.venv/bin/pytest -k elevacao_do_joelho        # um teste isolado
```

## Documentação

- [Arquitectura](docs/ARCHITECTURE.md) — abstracções centrais, pipeline, modelo
  de pontuação e de dados
- [Protocolo de captura](docs/CAPTURE.md) — definições de câmara, calibração,
  multicâmara

## Desportos

| Desporto | Perfil | Estado | Demo sintética |
|---|---|---|---|
| Ciclismo | [ciclismo.md](docs/sports/ciclismo.md) | `stable` | sim |
| Atletismo — corrida | [atletismo-corrida.md](docs/sports/atletismo-corrida.md) | `stable` | sim |
| Tiro com arco olímpico | [tiro-com-arco.md](docs/sports/tiro-com-arco.md) | `beta` | sim |
| Natação | [natacao.md](docs/sports/natacao.md) | `beta` | não |
| Lançamentos | [lancamentos.md](docs/sports/lancamentos.md) | `experimental` | não |

Acrescentar um desporto é escrever um perfil em `analisetecnica/sports/`, não
alterar o pipeline. Um teste verifica que `core/` nunca importa de `sports/`.

## Estado

Base funcional. Por implementar: tracking de objectos (arco, bicicleta, engenho),
triangulação multicâmara 3D, e a interface gráfica. Os limites de banda e os
pesos de pontuação são **pontos de partida a validar com treinadores**, não
constantes estabelecidas.
