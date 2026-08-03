# Perfil — Lançamentos

`id: athletics_throws` · `maturity: experimental`

Família de perfis: peso (linear e rotacional), disco, dardo, martelo. Partilham
estrutura de fases e a necessidade de tracking do engenho; divergem nas métricas
específicas.

**Perfil mais exigente dos cinco em termos de captura**, por três razões
independentes que se acumulam: velocidade elevada, rotação do atleta, e
dependência de medições métricas absolutas.

---

## Vistas

| Vista | Obrigatória | Plano | Lateralidade | Para quê |
|---|---|---|---|---|
| `lateral` | sim | sagital | direct | Ângulo e altura de largada, bloqueio da perna, inclinação do tronco |
| `posterior` | não | frontal | mirrored | Alinhamento, deslocamento lateral |
| `superior` | não | transverso | direct | Separação anca-ombro, trajectória do engenho em provas rotacionais |

**A noção de "vista lateral" degrada-se nas provas rotacionais.** No disco e no
martelo o atleta roda continuamente, pelo que a relação entre o corpo e a câmara
muda a cada frame e nenhuma vista fixa observa um plano constante. Consequência:
as métricas angulares em provas rotacionais têm validade reduzida em captura
monocular, e o sistema deve marcá-las como tal em vez de as apresentar como
equivalentes às restantes.

O dardo e o peso linear são substancialmente mais tratáveis: o movimento é
predominantemente ao longo de um eixo, e uma câmara perpendicular a esse eixo
observa um plano estável.

**Recomendação:** este perfil é o principal candidato a multicâmara com
triangulação 3D. A arquitectura já o prevê (`SyncGroup` com `extrinsics`), mas a
primeira versão monocular deve ser explicitamente rotulada como indicativa.

---

## Segmentação

```ts
{
  type: 'phase',
  phases: ['setup', 'approach', 'power_position', 'delivery', 'release', 'recovery'],
  events: ['approach_start', 'power_position_reached', 'release', 'recovery_end']
}
```

`approach` cobre o deslize no peso linear, as voltas no disco e no martelo, e a
corrida de balanço no dardo.

`release` — separação do engenho da mão — é o evento de referência e o mais
fiável de detectar por tracking do objecto. Praticamente todas as métricas de
resultado se avaliam nesse instante, o que faz da sua localização temporal o
factor determinante de precisão de todo o perfil. A 240 fps, um frame são ~4 ms;
a 30 fps, ~33 ms, durante os quais o engenho já percorreu vários metros.

---

## Objectos

```ts
[{
  id: 'implement',
  trackedPoints: ['center'],          // dardo: ['tip', 'tail', 'grip']
                                      // martelo: ['head', 'handle']
  tracker: 'detector'
}]
```

Tracking do engenho é obrigatório: sem ele não existem `release_angle`,
`release_velocity` nem `release_height`, que são as métricas de resultado do
perfil. O dardo exige dois pontos para determinar o ângulo de ataque face à
trajectória, distinção tecnicamente relevante e que um ponto único não capta.

---

## Filtragem

```ts
{ confidenceThreshold: 0.5, gapInterpolation: 'linear', maxGapFrames: 2,
  smoothing: { type: 'butterworth', order: 4, cutoffHz: 12 } }
```

Corte alto — a fase de entrega é muito rápida e uma suavização agressiva achata
precisamente os picos de velocidade que se pretende medir. Tolerância a falhas
baixa, porque interpolar sobre um movimento tão rápido inventa trajectória.

---

## Métricas

### Largada — métricas de resultado

| id | Cálculo | Vista | `requires` | `minFps` | `target` |
|---|---|---|---|---|---|
| `release_angle` | ângulo do vector velocidade do engenho face à horizontal no `release` | lateral | calibration | 240 | band |
| `release_velocity` | módulo da velocidade do engenho no `release` | lateral | calibration | 240 | maximize |
| `release_height` | altura do engenho no `release` ÷ estatura | lateral | none | 240 | maximize |
| `attack_angle` | (dardo) ângulo do eixo do dardo face ao vector velocidade | lateral | none | 240 | minimize |

`release_angle` e `release_velocity` são as únicas métricas do sistema inteiro
que exigem simultaneamente calibração métrica e cadência muito alta. São também
as mais valiosas tecnicamente. Em captura monocular sem calibração devem ser
omitidas do relatório, não estimadas — um ângulo de largada errado é pior do que
ângulo nenhum, porque orienta o treino na direcção errada.

### Posição de força e entrega

| id | Cálculo | Vista | `requires` | `target` | Bilateral |
|---|---|---|---|---|---|
| `hip_shoulder_separation` | diferença angular entre linha de ancas e linha de ombros na posição de força | superior | none | maximize | não |
| `block_leg_angle` | ângulo do joelho da perna de bloqueio no `release` | lateral | none | band | não |
| `block_leg_extension_rate` | velocidade de extensão do joelho de bloqueio na entrega | lateral | fps | maximize | não |
| `trunk_lean_release` | inclinação do tronco face à vertical no `release` | lateral | none | band | não |
| `front_hip_velocity` | velocidade horizontal da anca dianteira no `release` | lateral | calibration | minimize | não |
| `delivery_time` | duração entre `power_position_reached` e `release` | — | fps | minimize | não |

`hip_shoulder_separation` — a chamada separação ou *X-factor* — é o indicador
central de armazenamento elástico e o principal discriminante técnico da família.
Depende da vista superior, com a ressalva de deteção zenital já assinalada no
perfil de tiro com arco.

`front_hip_velocity` próximo de zero indica bloqueio eficaz do lado esquerdo (no
lançador destro): a energia transfere-se para o engenho em vez de continuar no
corpo. É contra-intuitivo o suficiente para merecer explicação no relatório.

### Aproximação

| id | Cálculo | Vista | `requires` | `target` |
|---|---|---|---|---|
| `approach_rhythm` | duração relativa das fases da aproximação | — | fps | match_reference |
| `com_path_deviation` | desvio lateral do centro de massa face ao eixo de lançamento ÷ estatura | posterior | none | minimize |
| `rotation_balance` | (provas rotacionais) estabilidade do eixo vertical durante as voltas | posterior | none | minimize |

---

## Pontuação (pesos iniciais, a validar)

| Grupo | Peso |
|---|---|
| Parâmetros de largada (`release_angle`, `release_velocity`, `release_height`) | 35% |
| Posição de força (`hip_shoulder_separation`, `trunk_lean_release`) | 25% |
| Bloqueio e entrega (`block_leg_angle`, `front_hip_velocity`, `delivery_time`) | 25% |
| Aproximação | 15% |

Se as métricas de largada não estiverem disponíveis por falta de calibração ou
cadência, o score deve ser recalculado sobre os grupos restantes **e assinalado
como parcial** — nunca apresentado como equivalente a um score completo.

---

## Riscos

- **Rotação do atleta invalida o pressuposto de plano fixo** no disco e no
  martelo. Sem multicâmara, estas duas provas ficam limitadas a métricas
  temporais e de fase.
- **Cadência exigida acima do típico.** 240 fps é o mínimo para a largada, e a
  essa cadência a resolução desce e a exigência de luz sobe.
- **Desfoque de movimento** apaga a mão e o engenho no instante mais importante
  do gesto. Obturador rápido é aqui inegociável.
- **Rolling shutter** com velocidade angular elevada distorce a geometria do
  frame de largada.
- **Segurança de filmagem.** O posicionamento de câmaras e tripés tem de respeitar
  os sectores de queda; um tripé com telemóvel dentro do sector é risco material.
  Restrição operacional, mas real.

Sugestão de faseamento: começar por **peso linear e dardo**, onde o movimento é
predominantemente planar, e adiar disco e martelo para depois de existir
triangulação multicâmara.
