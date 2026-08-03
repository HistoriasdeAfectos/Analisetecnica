# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Comandos

Python ≥3.10, sem build step. Não há linter configurado.

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"   # instalar
.venv/bin/pytest                                            # todos os testes
.venv/bin/pytest tests/test_arquitectura.py                 # só as invariantes
.venv/bin/pytest -k elevacao_do_joelho                      # um teste isolado
.venv/bin/analisetecnica demo --perfil ciclismo             # pipeline sem vídeo
.venv/bin/analisetecnica perfis --detalhe                   # métricas por perfil
```

O backend de pose real é opcional (`pip install -e ".[pose]"`) e exige o modelo
`models/pose_landmarker.task` — ver README. Sem ele, `--backend synthetic` e os
ficheiros JSON de keypoints cobrem todo o pipeline, que é como os testes correm.

A documentação e o código estão em português europeu — manter, incluindo em
comentários, nomes de perfis e mensagens de commit. Identificadores de métrica
mantêm-se como estão nos documentos (`knee_lift_height`, `anchor_consistency`).

## Onde está o quê

- `analisetecnica/core/` — pipeline agnóstico ao desporto.
- `analisetecnica/sports/` — um módulo por desporto; importar o pacote regista-os.
- `analisetecnica/sports/_common.py` — fábricas de métricas partilhadas. Vive em
  `sports/` de propósito: é conveniência para escrever perfis, não parte do núcleo.
- `tests/test_arquitectura.py` — as invariantes abaixo, verificadas
  automaticamente. Se alterar a estrutura, é aqui que se vê o que se partiu.

## Documentos de desenho

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — abstracções centrais, pipeline,
  modelo de pontuação e de dados. **Fonte de verdade** para qualquer decisão
  estrutural; o código segue-o, e divergências são para corrigir num dos dois.
- [`docs/CAPTURE.md`](docs/CAPTURE.md) — protocolo de captura, calibração,
  sincronização multicâmara.
- [`docs/sports/`](docs/sports/) — um perfil por desporto, com métricas, bandas e
  riscos. Cada módulo em `sports/` implementa o documento homónimo.

## O que o software faz

Análise técnica corporal a partir de vídeo e fotografia de telemóvel. Deteção de
pose 2D (MediaPipe por omissão) → métricas biomecânicas → comparação com bandas
de referência de elite ou com o histórico do próprio atleta → relatório e score
de evolução. Multidesporto por desenho.

## Invariantes de arquitectura

Estas regras são o que impede a base de se tornar específica de um desporto.
Violá-las é o modo de falha principal deste projecto.

1. **Nada em `core/` importa de `sports/`.** Se for preciso, falta uma
   abstracção — criar a abstracção, não a excepção.
2. **Acrescentar um desporto é escrever um perfil**, nunca alterar o pipeline.
3. **Métricas adimensionais primeiro.** Cada métrica declara
   `requires: 'none' | 'fps' | 'calibration'`. Havendo alternativa adimensional
   para a mesma pergunta técnica, usar essa — dispensa calibração e torna o valor
   comparável entre atletas de estaturas diferentes.
4. **Keypoints em bruto são retidos permanentemente.** As fórmulas vão mudar; sem
   os keypoints, todo o histórico fica incomparável a cada afinação. Cada
   `MetricResult` regista a versão da definição que o produziu.
5. **Score técnico e score de evolução nunca se fundem.** Um atleta pode melhorar
   muito e continuar nos 60. Um número único esconde as duas informações.
6. **Nunca diferença percentual sobre valores que podem aproximar-se de zero**
   (queda da anca, desvio lateral) — a divisão explode. Usar desvio absoluto com
   limiar próprio, ou desvios-padrão da banda de referência.
7. **Referência é sempre banda (média ± desvio), nunca um vídeo único.** `n=1` é
   assinalado como referência fraca.
8. **Todo o score carrega indicador de confiança** — confiança da pose, fps
   efectivo, presença de calibração, número de repetições. Apresentar em bandas
   de 5 pontos; `87,3` sugere exactidão que a pose 2D não tem.
9. **O texto de recomendação vive na `MetricSpec`.** Centralizá-lo transforma o
   relatório num `switch` por desporto.

## Armadilhas específicas

- **Lateralidade.** As vistas `posterior` e `inferior` têm
  `lateralityMapping: 'mirrored'` — o eixo esquerda/direita da imagem inverte-se.
  Trocá-lo inverte silenciosamente toda a análise de simetria.
- **Filtragem é obrigatória** entre pose e cálculo. **Excepção:** as métricas de
  tremor e estabilidade (tiro com arco) calculam-se sobre o sinal *antes* da
  suavização — filtrar removeria o que se pretende medir.
- **Modo fotografia exige `taggedEvent`**, e só é comparável com capturas do mesmo
  evento. Comparar elevação do joelho entre fotos de fases diferentes produz uma
  diferença sem relação com evolução técnica.
- **`bilateral: false` no tiro com arco** — a postura é deliberadamente
  assimétrica; simetria não é objectivo.
- **Ciclismo segmenta por ângulo de manivela, não por tempo.** É o equivalente ao
  0–100% da passada.
- **Passada vs passo na corrida.** Cadência reporta-se em passos/min ≈ 2 ×
  passadas/min. A unidade é guardada explicitamente para evitar o erro de factor 2.

## Valores de referência

Todos os limites de banda e pesos de pontuação nos perfis são **pontos de partida
a validar com treinadores**, não constantes estabelecidas. Não os endurecer em
código sem essa validação, e mantê-los editáveis na interface — os pesos são
juízo de treinador.

## Por implementar

- **Tracking de objectos** (arco, bicicleta, engenho). Bloqueia as métricas de
  deriva da mira no arco e de ângulo/velocidade de largada nos lançamentos.
- **Triangulação multicâmara 3D.** O modelo de dados já a prevê (`SyncGroup`),
  o cálculo não existe.
- **Geradores sintéticos** para natação e lançamentos — os outros três têm.
- **Interface gráfica**, incluindo a revisão manual dos eventos de contacto, que
  o perfil de corrida assume existir.

## Riscos técnicos assumidos

Documentados nos perfis respectivos; não os re-descobrir nem os ignorar:

- Deteção zenital (vista `superior`, usada no arco e nos lançamentos) está fora da
  distribuição de treino do MediaPipe. Validar com vídeo real antes de qualquer
  métrica depender dela; plano B é anotação assistida.
- Deteção de contacto no solo na corrida é o ponto mais frágil do pipeline —
  prever revisão manual dos eventos na interface.
- Natação exigirá previsivelmente um backend de pose afinado; é a razão de
  `PoseBackend` ser configurável por desporto.
- Disco e martelo: a rotação contínua invalida o pressuposto de plano fixo em
  captura monocular.

## Notas legais

- Vídeo de atletas olímpicos proveniente de transmissões tem direitos de autor e
  de imagem. Referências pré-carregadas com esse material exigem licenciamento.
- Se o backend de pose vier a mudar para OpenPose, confirmar licenciamento: o uso
  comercial requer licença da CMU.
