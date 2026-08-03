# Perfil — Tiro com arco olímpico (recurvo)

`id: archery_recurve` · `maturity: beta`

Desporto de precisão com postura **deliberadamente assimétrica**: `bilateral` é
`false` em quase todas as métricas. O que se mede não é simetria — é
**repetibilidade entre tiros**.

Diferença estrutural face à corrida e ao ciclismo: não há ciclo. Há uma sequência
de fases discretas, e a maior parte das métricas avalia-se em instantes ou em
janelas de manutenção estática.

---

## Vistas

| Vista | Obrigatória | Plano | Lateralidade | Para quê |
|---|---|---|---|---|
| `posterior` | sim | frontal | mirrored | Postura vertical, altura dos ombros, inclinação da cabeça, alinhamento da corda |
| `superior` | não | transverso | direct | Alinhamento da linha de ombros e do antebraço de tração face à linha de tiro |
| `lateral` | não | sagital | direct | Inclinação do tronco, extensão do braço do arco |

A vista posterior é a principal: colocada atrás do atirador, alinhada com a linha
de tiro. **Atenção à lateralidade** — nesta vista o eixo esquerda/direita da
imagem inverte-se face à frontal, e trocá-lo inverte a identificação de braço do
arco e braço de tração.

**A vista superior é o maior risco técnico do projecto.** O MediaPipe é treinado
com imagens de pessoas vistas de frente ou de lado; uma vista zenital está fora
da distribuição de treino e a deteção degrada consideravelmente. Deve ser testada
com vídeo real antes de qualquer métrica depender dela. Alternativas se falhar:
anotação assistida dos poucos pontos necessários (ombros, cotovelo, punhos), que
num gesto quase estático é perfeitamente viável.

---

## Segmentação

```ts
{
  type: 'phase',
  phases: ['stance', 'nock', 'setup', 'draw', 'anchor', 'expansion', 'release', 'follow_through'],
  events: ['draw_start', 'anchor_reached', 'release', 'follow_through_end']
}
```

`release` é o evento mais fiável de detectar — a separação da corda e a partida
da flecha produzem uma descontinuidade nítida no tracking do objecto. Serve de
âncora temporal para localizar as fases restantes.

A janela de `anchor` + `expansion` é a mais informativa: é aí que se medem
estabilidade e tremor.

---

## Objectos

```ts
[{
  id: 'bow',
  trackedPoints: ['riser_center', 'upper_limb_tip', 'lower_limb_tip', 'string_nock', 'sight_pin'],
  tracker: 'detector'
}, {
  id: 'arrow',
  trackedPoints: ['nock', 'point'],
  tracker: 'detector'
}]
```

Nenhum modelo de pose deteta um arco. Este subsistema é obrigatório aqui, não
acessório. O arco é rígido e move-se pouco durante a fase de âncora, o que
favorece anotação num frame com propagação por tracking.

---

## Filtragem

```ts
{ confidenceThreshold: 0.6, gapInterpolation: 'linear', maxGapFrames: 2,
  smoothing: { type: 'butterworth', order: 2, cutoffHz: 3 } }
```

Limiar de confiança mais exigente e corte baixo: o gesto é lento e o que
interessa são desvios pequenos. **Excepção importante:** as métricas de tremor
(`bow_hand_stability`, `aim_drift`) devem ser calculadas sobre o sinal **antes**
da suavização — filtrar o sinal removeria precisamente aquilo que se pretende
medir.

---

## Métricas

### Postura e alinhamento

| id | Cálculo | Vista | `requires` | `target` | Bilateral |
|---|---|---|---|---|---|
| `bow_arm_extension` | ângulo(ombro, cotovelo, punho) do braço do arco na âncora | posterior/lateral | none | band | não |
| `bow_shoulder_height` | altura do ombro do arco − altura do ombro de tração ÷ largura dos ombros | posterior | none | band | não |
| `draw_elbow_alignment` | ângulo do antebraço de tração face à linha da flecha | superior | none | band | não |
| `shoulder_line_alignment` | ângulo da linha de ombros face à linha de tiro | superior | none | band | não |
| `hip_shoulder_alignment` | diferença angular entre linha de ancas e linha de ombros | superior | none | minimize | não |
| `spine_vertical` | desvio do eixo anca→ombro face à vertical | posterior | none | minimize | não |
| `head_tilt` | ângulo da cabeça face à vertical | posterior | none | minimize | não |
| `stance_width` | separação dos tornozelos ÷ largura dos ombros | posterior | none | band | não |

`bow_shoulder_height` traduz um dos pontos técnicos centrais do recurvo: ombro do
arco baixo. `spine_vertical` capta a inclinação para trás, defeito comum de
compensação de peso do arco.

`bow_arm_extension` tem faixa óptima — braço demasiado flectido perde estrutura,
braço em hiperextensão bloqueada expõe o cotovelo à passagem da corda.

### Estabilidade e repetibilidade — o núcleo do perfil

| id | Cálculo | Vista | `requires` | `target` |
|---|---|---|---|---|
| `anchor_consistency` | desvio-padrão, entre tiros, da distância mão de tração ↔ referência facial ÷ largura da cabeça | posterior | none | consistency |
| `bow_hand_stability` | amplitude do tremor do punho do arco durante a janela de mira ÷ largura dos ombros | posterior | fps | minimize |
| `aim_drift` | deriva do `sight_pin` durante a janela de mira | posterior | fps | minimize |
| `draw_length_consistency` | desvio-padrão do comprimento de tração entre tiros | posterior | none | consistency |
| `posture_repeatability` | desvio-padrão agregado das métricas posturais entre tiros | todas | none | consistency |
| `release_direction` | direcção do deslocamento da mão de tração após a largada | posterior | fps | band |
| `follow_through_duration` | tempo entre `release` e fim do acompanhamento | — | fps | band |

Estas métricas resolvem o problema de fundo do perfil: **a precisão exigida no
arco é de escala inferior ao ruído da pose 2D**. A consistência do ponto de
âncora é milimétrica, e o erro do detector num frame isolado pode ser maior do
que o desvio a medir. Ao medir a **variância entre N tiros**, o ruído aleatório
cancela-se parcialmente e o que sobressai é a variabilidade real do atleta — que
é, de qualquer forma, o que interessa ao treinador.

Consequência prática: **uma sessão de arco tem de conter várias flechas.** Uma
análise de tiro único não é interpretável e a interface deve impedi-la, exigindo
um mínimo (sugestão: 6 tiros, uma série).

---

## Pontuação (pesos iniciais, a validar)

| Grupo | Peso |
|---|---|
| Repetibilidade (`anchor_consistency`, `draw_length_consistency`, `posture_repeatability`) | 40% |
| Alinhamento (`shoulder_line_alignment`, `draw_elbow_alignment`, `hip_shoulder_alignment`) | 25% |
| Postura (`bow_shoulder_height`, `spine_vertical`, `head_tilt`, `stance_width`) | 20% |
| Estabilidade (`bow_hand_stability`, `aim_drift`) | 15% |

Peso dominante na repetibilidade — é a característica que distingue níveis neste
desporto, e é também a família de métricas mais robusta ao ruído do detector.

---

## Riscos

- **Vista superior fora da distribuição de treino do MediaPipe.** Validar cedo,
  com plano B em anotação assistida.
- **Sinal abaixo do ruído em métricas absolutas.** Mitigado pelo desenho centrado
  em variância, mas as métricas posturais absolutas devem ser apresentadas com
  margem explícita.
- **Oclusão do braço de tração pelo tronco** na vista posterior, dependendo da
  posição da câmara. Ajustável com ligeiro desvio lateral, ao custo de introduzir
  erro de projecção — compromisso a documentar no protocolo.
- **Sem calibração métrica não há medidas absolutas de comprimento de tração**;
  por isso todas as distâncias são normalizadas por segmentos corporais.
