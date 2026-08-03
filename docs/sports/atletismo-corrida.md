# Perfil — Atletismo, corrida

`id: athletics_running` · `maturity: stable`

Provas: velocidade (100/200/400 m), meio-fundo e fundo. As bandas de referência
são por prova — o padrão técnico de um velocista e de um fundista diferem em
inclinação do tronco, elevação do joelho e tempo de contacto.

---

## Vistas

| Vista | Obrigatória | Plano | Lateralidade | Para quê |
|---|---|---|---|---|
| `lateral` | sim | sagital | direct | Ângulos articulares, tronco, contacto no solo, apoio do pé |
| `frontal` | não | frontal | direct | Queda da anca, cruzamento de braços, alinhamento |
| `posterior` | não | frontal | mirrored | Queda da anca, pronação/supinação, simetria |

Zona de análise marcada no solo, com o atleta já em velocidade constante — a
técnica em aceleração é outra e não deve ser comparada com a de velocidade
mantida.

---

## Segmentação

```ts
{ type: 'cyclic', cycleEvent: 'footstrike_right', normalizeTo: 'percent' }
```

**Definições explícitas**, porque a ambiguidade aqui contamina metade das
métricas:

- **Passada (*stride*)** — do primeiro contacto de um pé ao contacto seguinte do
  **mesmo** pé. É o ciclo.
- **Passo (*step*)** — de um pé ao outro. Meia passada.
- **Cadência** — reportada em **passos por minuto** (≈ 2 × passadas/min). O campo
  guarda a unidade explicitamente para evitar o erro de factor 2.

Eventos detectados: `footstrike`, `midstance`, `toe_off`, `peak_knee_lift`,
`peak_vertical`.

---

## Filtragem

```ts
{ confidenceThreshold: 0.5, gapInterpolation: 'spline', maxGapFrames: 3,
  smoothing: { type: 'butterworth', order: 4, cutoffHz: 10 } }
```

Corte mais alto que no ciclismo — o movimento é mais rápido e um corte agressivo
achata os picos de contacto.

---

## Métricas

### Membros inferiores

| id | Cálculo | Vista | `requires` | `minFps` | `target` | Bilateral |
|---|---|---|---|---|---|---|
| `knee_angle` | ângulo(anca, joelho, tornozelo), curva 0–100% | lateral | none | 60 | match_reference | sim |
| `hip_angle` | ângulo(ombro, anca, joelho) | lateral | none | 60 | match_reference | sim |
| `ankle_angle` | ângulo(joelho, tornozelo, foot_index) | lateral | none | 60 | match_reference | sim |
| `knee_lift_height` | altura máxima do joelho acima da anca ÷ comprimento da perna | lateral | none | 60 | band | sim |
| `heel_recovery` | altura mínima do calcanhar face à nádega ÷ comprimento da perna | lateral | none | 60 | band | sim |
| `overstride` | distância horizontal tornozelo↔centro de massa no contacto ÷ comprimento da perna | lateral | none | 120 | minimize | sim |

`knee_lift_height` é a métrica que responde directamente a *"o atleta está a
levantar melhor o joelho?"*. É adimensional — normalizada pelo comprimento da
perna do próprio atleta — portanto **não exige calibração nem cadência alta**, e
é comparável entre sessões e entre atletas de estaturas diferentes. Em modo
fotografia, exige `taggedEvent: 'peak_knee_lift'`.

### Pé e contacto

| id | Cálculo | Vista | `requires` | `minFps` | `target` |
|---|---|---|---|---|---|
| `ground_contact_time` | duração entre `footstrike` e `toe_off` (ms) | lateral | fps | 120 | minimize |
| `flight_time` | duração sem contacto (ms) | lateral | fps | 120 | match_reference |
| `foot_strike_type` | posição vertical relativa calcanhar↔`foot_index` no primeiro contacto → calcanhar / médio / antepé | lateral | fps | 120 | match_reference |
| `foot_contact_angle` | ângulo(joelho, tornozelo, foot_index) no `footstrike` | lateral | none | 120 | band |
| `pronation_deviation` | desvio lateral do eixo do pé face ao eixo de progressão | posterior | none | 120 | band |

`foot_contact_angle` é a métrica de *"coloca melhor a biqueira no chão?"*.
Requer 120 fps para que o frame do primeiro contacto seja identificado com
precisão suficiente — a 30 fps o frame capturado pode já estar em plena fase de
apoio.

**`pronation_deviation` é estimativa aproximada, não medição clínica.** A
pronação é um movimento subtalar fino, normalmente medido com marcadores
dedicados e câmara de alta velocidade focada no pé. O relatório deve apresentá-la
como indicação, com essa ressalva visível, para não induzir o treinador em erro.

### Tronco e bacia

| id | Cálculo | Vista | `requires` | `target` |
|---|---|---|---|---|
| `trunk_lean` | ângulo(anca, ombro, orelha) face à vertical | lateral | none | band |
| `pelvic_drop` | diferença de altura entre ancas na fase de apoio ÷ largura da bacia | frontal/posterior | none | minimize |
| `vertical_oscillation` | amplitude vertical do centro de massa ÷ estatura | lateral | none | minimize |

Centro de massa aproximado pela média ponderada dos keypoints de tronco e ancas.
Normalizado pela estatura para dispensar calibração.

`trunk_lean` tem faixa óptima, não direcção: 0° (tronco vertical rígido) e 20°
são ambos defeitos. É o exemplo canónico de porque `target: band` existe.

### Membros superiores

| id | Cálculo | Vista | `requires` | `target` |
|---|---|---|---|---|
| `shoulder_angle_rom` | amplitude de ângulo(tronco, ombro, cotovelo) no ciclo | lateral | none | band |
| `elbow_angle` | ângulo(ombro, cotovelo, punho), média no ciclo | lateral | none | band |
| `arm_crossover` | ultrapassagem da linha média pelo punho ÷ largura dos ombros | frontal | none | minimize |
| `arm_leg_sync` | correlação cruzada entre fase do braço e fase da perna contralateral | lateral | fps | maximize |

### Simetria

| id | Cálculo | `target` |
|---|---|---|
| `contact_time_symmetry` | \|contacto esq − contacto dir\| ÷ média | minimize |
| `knee_angle_symmetry` | \|θ esq − θ dir\| nos eventos-chave | minimize |
| `arm_rom_symmetry` | \|ROM braço esq − ROM braço dir\| | minimize |
| `stride_symmetry` | \|duração passo esq − passo dir\| ÷ média | minimize |

---

## Pontuação (pesos iniciais, a validar)

| Grupo | Peso |
|---|---|
| Mecânica dos membros inferiores (`knee_lift_height`, `heel_recovery`, `overstride`) | 25% |
| Contacto e apoio do pé (`ground_contact_time`, `foot_strike_type`, `foot_contact_angle`) | 25% |
| Postura do tronco e bacia (`trunk_lean`, `pelvic_drop`, `vertical_oscillation`) | 25% |
| Membros superiores | 10% |
| Simetria | 15% |

Bandas de referência distintas por prova. Um velocista tem elevação de joelho e
inclinação de tronco substancialmente superiores às de um fundista; comparar um
fundista com banda de velocidade produziria um relatório inteiramente enganador.

---

## Riscos

- **Deteção de contacto no solo é o ponto mais frágil do pipeline.** Os keypoints
  do pé são os menos estáveis do MediaPipe. A heurística de altura mínima +
  velocidade próxima de zero funciona, mas exige suavização e tolera mal cadências
  baixas. Prever revisão manual dos eventos detectados na interface — não tratar
  como totalmente automático na primeira versão.
- **Oclusão do membro afastado** na vista lateral, como no ciclismo. Simetria
  fiável quer duas câmaras laterais sincronizadas.
- **Velocidade não constante** entre sessões invalida a comparação. Registar o
  ritmo nos metadados e recusar comparações fora de uma tolerância.
