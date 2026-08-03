# Perfil — Natação

`id: swimming` · `maturity: beta`

Perfil por estilo: crol, costas, bruços, mariposa. As métricas abaixo estão
escritas para **crol**; os restantes estilos partilham a estrutura e trocam as
métricas específicas de braçada e pernada.

---

## Vistas

| Vista | Obrigatória | Plano | Lateralidade | Para quê |
|---|---|---|---|---|
| `inferior` | sim | frontal/transverso | mirrored | Câmara submersa por baixo do nadador. Trajectória das mãos, cotovelo alto na chamada, rolamento do corpo |
| `superior` | não | transverso | direct | Câmara acima da água. Entrada das mãos, cruzamento da linha média, alinhamento |
| `lateral` | não | sagital | direct | Câmara submersa lateral. Amplitude da pernada, posição da anca, alinhamento horizontal |

**A câmara submersa é o que torna este perfil viável.** Uma câmara totalmente
dentro de água elimina a interface ar-água, que é a principal fonte de distorção
geométrica: filmar da superfície através da fronteira ar-água introduz refracção
variável com o ângulo e com o estado da superfície, e é praticamente
incorrigível. Submersa, resta apenas a refracção da porta da caixa estanque —
que é fixa, conhecida e **calibrável**.

Consequência para o protocolo: a calibração tem de ser feita **debaixo de água**,
com padrão de xadrez ou ChArUco submerso. Uma calibração feita em ar não é válida
em água. O tipo de porta importa: uma porta plana introduz distorção radial
significativamente maior do que uma porta em domo.

A vista `superior` atravessa a interface e serve sobretudo para observação
qualitativa e para métricas angulares no plano transverso; não deve suportar
medições de distância.

---

## Segmentação

```ts
{ type: 'cyclic', cycleEvent: 'hand_entry_right', normalizeTo: 'percent' }
```

Ciclo de braçada: da entrada de uma mão à entrada seguinte da mesma mão. Fases
internas: `entry`, `catch`, `pull`, `push`, `recovery`.

---

## Calibração

A piscina é um ambiente privilegiado: **as marcações do fundo e as balizas de
raia têm dimensões regulamentares conhecidas** e funcionam como calibração
permanente no enquadramento, sem necessidade de colocar objectos. Isto torna
viáveis as métricas de distância — nomeadamente `stroke_length` — que noutros
desportos exigiriam preparação adicional.

---

## Filtragem

```ts
{ confidenceThreshold: 0.4, gapInterpolation: 'spline', maxGapFrames: 6,
  smoothing: { type: 'butterworth', order: 4, cutoffHz: 5 } }
```

Limiar de confiança mais baixo e tolerância a falhas maior do que nos outros
perfis: a deteção é intrinsecamente mais ruidosa em meio aquático, e um limiar
exigente descartaria a maioria dos frames. Em contrapartida, exige marcação de
validade mais agressiva no relatório.

---

## Métricas

### Braçada

| id | Cálculo | Vista | `requires` | `target` | Bilateral |
|---|---|---|---|---|---|
| `elbow_angle_catch` | ângulo(ombro, cotovelo, punho) na fase de chamada | inferior | none | band | sim |
| `high_elbow_index` | altura do cotovelo face ao punho na chamada ÷ comprimento do antebraço | inferior | none | maximize | sim |
| `hand_entry_offset` | desvio lateral da entrada da mão face à linha do ombro ÷ largura dos ombros | superior | none | band | sim |
| `hand_path_width` | amplitude lateral da trajectória da mão ÷ largura dos ombros | inferior | none | band | sim |
| `midline_crossover` | ultrapassagem da linha média pela mão ÷ largura dos ombros | superior/inferior | none | minimize | sim |
| `stroke_rate` | ciclos por minuto | fps | match_reference | não |
| `stroke_length` | distância percorrida por ciclo | calibration | maximize | não |

`high_elbow_index` traduz o conceito técnico de *early vertical forearm* — o
cotovelo alto na chamada é um dos discriminantes centrais entre níveis no crol, e
a vista inferior é a única que o mostra com clareza.

### Posição do corpo

| id | Cálculo | Vista | `requires` | `target` |
|---|---|---|---|---|
| `body_roll` | amplitude de rotação da linha de ombros no ciclo | inferior | none | band |
| `body_roll_symmetry` | \|rolamento esq − rolamento dir\| | inferior | none | minimize |
| `hip_depth` | profundidade da anca face ao eixo horizontal ÷ estatura | lateral | none | minimize |
| `head_alignment` | ângulo cabeça↔tronco | lateral | none | band |
| `lateral_deviation` | oscilação lateral do eixo do corpo ÷ estatura | superior | none | minimize |

`hip_depth` é o indicador central de arrasto: ancas baixas aumentam a secção
frontal. Cruza com `head_alignment`, já que a elevação da cabeça é a causa mais
frequente.

### Pernada

| id | Cálculo | Vista | `requires` | `target` | Bilateral |
|---|---|---|---|---|---|
| `kick_amplitude` | excursão vertical do tornozelo ÷ comprimento da perna | lateral | none | band | sim |
| `kick_count` | pernadas por ciclo de braçada | lateral | fps | match_reference | não |
| `knee_flexion_kick` | flexão máxima do joelho na pernada | lateral | none | band | sim |

### Respiração e simetria

| id | Cálculo | Vista | `requires` | `target` |
|---|---|---|---|---|
| `breathing_rotation` | rotação adicional da cabeça no ciclo com respiração | superior/inferior | none | minimize |
| `stroke_symmetry` | \|duração fase esq − fase dir\| ÷ média | inferior | fps | minimize |

`breathing_rotation` isola o custo técnico da respiração: quanto o ciclo com
respiração se desvia do ciclo sem. Requer identificar quais os ciclos com
respiração, o que é detectável pela rotação da cabeça.

---

## Pontuação (pesos iniciais, a validar)

| Grupo | Peso |
|---|---|
| Mecânica da braçada (`high_elbow_index`, `elbow_angle_catch`, `hand_path_width`) | 35% |
| Posição do corpo (`hip_depth`, `head_alignment`, `body_roll`, `lateral_deviation`) | 30% |
| Pernada | 15% |
| Simetria e respiração | 20% |

---

## Riscos

Este é o perfil com maior distância entre desenho e implementação funcional.

- **Modelo de pose fora da distribuição de treino.** O MediaPipe é treinado com
  pessoas em pé, vestidas, em ar. Um nadador em decúbito ventral, submerso, de
  fato de banho, visto de baixo, é um caso substancialmente diferente. É
  previsível que o backend genérico não chegue e que seja necessário afinar um
  modelo com dados anotados de natação — o que é a razão principal para
  `PoseBackend` ser configurável por desporto.
- **Turbulência e bolhas** ocluem membros precisamente nas fases mais
  informativas (chamada e tração). Daí a tolerância a falhas mais alta na
  filtragem.
- **Refracção da porta da caixa estanque**, mitigada por calibração submersa mas
  não eliminada; agrava-se na periferia do enquadramento.
- **Luz.** Obturador rápido exige luz, e a piscina coberta costuma ter pouca.
  Pode ser necessário aceitar cadências mais baixas ou usar iluminação adicional.

Sugestão de faseamento: começar pelas métricas de vista `inferior` com o nadador
em velocidade constante no centro da raia, onde a turbulência é menor e a
distância à câmara é conhecida. Adiar `superior` e a análise de viragens.
