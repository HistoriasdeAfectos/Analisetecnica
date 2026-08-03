# Perfil — Ciclismo

`id: cycling` · `maturity: stable` · **primeiro desporto a implementar**

Ambiente mais favorável de todos os cinco: câmara fixa, atleta em rolo, movimento
planar e perpendicular à câmara, iluminação controlada, repetição indefinida.
Serve para validar todo o pipeline antes de enfrentar rotação, água e oclusão.

Cobre dois modos:
- **Dinâmico** — pedalada em movimento (segmentação `cyclic`).
- **Estático** — bike fit, postura parada (segmentação `instant`). Exercita o
  modo fotografia desde o início.

---

## Vistas

| Vista | Obrigatória | Plano | Lateralidade | Para quê |
|---|---|---|---|---|
| `lateral` | sim | sagital | direct | Ângulos articulares, tronco, posição sobre a bicicleta |
| `frontal` | não | frontal | direct | Desvio medial-lateral do joelho, assimetria de ombros |
| `posterior` | não | frontal | mirrored | Balanço da bacia no selim |

Lado a filmar na vista lateral: registar qual, e manter entre sessões. O lado
mais próximo da câmara ocluí o oposto.

---

## Segmentação

```ts
{
  type: 'cyclic',
  cycleEvent: 'crank_tdc',        // ponto morto superior
  normalizeTo: 'percent',
  phaseVariable: 'crank_angle'    // 0–360°
}
```

**Normalizar por ângulo da manivela, não por tempo.** É o equivalente ao 0–100%
da passada e torna a comparação independente da cadência. Convenção: 0° = ponto
morto superior (TDC), 180° = ponto morto inferior (BDC), 90° = posição das três
horas.

Modo estático: `{ type: 'instant', events: ['neutral_position'] }`.

---

## Objectos

```ts
[{
  id: 'bike',
  trackedPoints: ['bottom_bracket', 'crank_end', 'pedal_spindle', 'saddle_nose', 'handlebar', 'hub_rear'],
  tracker: 'assisted'
}]
```

Bicicleta em rolo é quase estática no enquadramento: basta anotar num frame e
propagar. Só a manivela e o pedal precisam de tracking contínuo — e são eles que
fornecem o `crank_angle` e a cadência.

---

## Filtragem

```ts
{ confidenceThreshold: 0.5, gapInterpolation: 'spline', maxGapFrames: 4,
  smoothing: { type: 'butterworth', order: 4, cutoffHz: 6 } }
```

---

## Métricas

### Membros inferiores — dinâmico

| id | Cálculo | Vista | `requires` | `target` | Bilateral |
|---|---|---|---|---|---|
| `knee_angle_bdc` | ângulo(anca, joelho, tornozelo) a 180° de manivela | lateral | none | band | sim |
| `knee_angle_tdc` | mesmo ângulo a 0° | lateral | none | band | sim |
| `knee_rom` | amplitude do ângulo do joelho no ciclo | lateral | none | band | sim |
| `hip_angle_min` | ângulo(ombro, anca, joelho) mínimo no ciclo | lateral | none | band | sim |
| `ankle_rom` | amplitude do ângulo do tornozelo (padrão de *ankling*) | lateral | none | band | sim |
| `knee_lateral_travel` | desvio medial-lateral do joelho ÷ comprimento do fémur | frontal | none | minimize | sim |
| `kops_offset` | desvio horizontal joelho↔eixo do pedal às 3 horas ÷ comprimento da tíbia | lateral | none | band | sim |

`knee_angle_bdc` é a métrica central do bike fit: flexão insuficiente indica
selim alto (com risco de compensação por balanço da bacia), flexão excessiva
indica selim baixo. Valores indicativos correntes situam-se na ordem dos 30–40°
de flexão, mas **os limites da banda devem ser validados com treinador** antes de
serem usados para pontuar.

### Tronco e membros superiores

| id | Cálculo | Vista | `requires` | `target` |
|---|---|---|---|---|
| `trunk_angle` | ângulo do segmento anca→ombro face à horizontal | lateral | none | band |
| `elbow_angle` | ângulo(ombro, cotovelo, punho) | lateral | none | band |
| `neck_extension` | ângulo(ombro, orelha, olho) — carga cervical | lateral | none | band |
| `shoulder_drop` | diferença de altura entre ombros ÷ largura dos ombros | frontal | none | minimize |

### Bacia

| id | Cálculo | Vista | `requires` | `target` |
|---|---|---|---|---|
| `pelvic_rock` | amplitude vertical da diferença entre ancas no ciclo ÷ largura da bacia | posterior | none | minimize |

Balanço da bacia é o principal indicador indirecto de selim demasiado alto e
cruza com `knee_angle_bdc` na geração de recomendações.

### Temporais e de simetria

| id | Cálculo | `requires` | `target` |
|---|---|---|---|
| `cadence` | rotações da manivela por minuto | fps | match_reference |
| `knee_rom_symmetry` | \|ROM esquerdo − ROM direito\| | none | minimize |
| `phase_symmetry` | desfasamento entre picos esquerdo e direito face a 180° | fps | minimize |

### Estático (bike fit)

| id | Cálculo | `requires` |
|---|---|---|
| `saddle_height` | eixo pedaleiro → topo do selim | calibration |
| `saddle_setback` | recuo horizontal da ponta do selim face ao eixo pedaleiro | calibration |
| `reach` | ponta do selim → guiador | calibration |
| `drop` | diferença de altura selim ↔ guiador | calibration |

Únicas métricas do perfil que exigem calibração métrica — são medidas de
montagem, não de técnica.

---

## Pontuação (pesos iniciais, a validar)

| Grupo | Peso |
|---|---|
| Extensão do joelho (`knee_angle_bdc`, `knee_angle_tdc`, `knee_rom`) | 30% |
| Alinhamento do joelho (`knee_lateral_travel`, `kops_offset`) | 20% |
| Estabilidade da bacia (`pelvic_rock`) | 15% |
| Tronco e pescoço (`trunk_angle`, `neck_extension`, `elbow_angle`) | 20% |
| Simetria | 15% |

---

## Riscos

- **Oclusão do lado afastado.** O membro próximo da câmara tapa o oposto na vista
  lateral. Simetria fiável exige duas câmaras laterais (uma de cada lado) no
  mesmo `SyncGroup`, ou duas séries em lados opostos com a limitação assinalada.
- **Confusão pose/bicicleta.** O quadro e a roda podem induzir keypoints falsos.
  Vale validar com fundo contrastante.
- **`ankle_rom`** depende de keypoints do pé, os menos estáveis do modelo. Se a
  confiança for baixa, marcar em vez de pontuar.
