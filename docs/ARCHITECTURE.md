# Arquitectura — Analisetecnica

Software de análise técnica corporal por vídeo e fotografia, multidesporto.

Este documento define as abstracções centrais. Os perfis concretos de cada
desporto estão em [`docs/sports/`](sports/). O protocolo de captura está em
[`CAPTURE.md`](CAPTURE.md).

> **Estado:** documento de desenho. Ainda não existe implementação, e a stack
> técnica não está escolhida. Os schemas abaixo usam notação TypeScript por
> legibilidade — não constituem compromisso com a linguagem.

---

## 1. Princípios

**1.1 Nada específico de um desporto no núcleo.**
Vistas, métricas, segmentação temporal, referências e pesos de pontuação são
declarados por perfil de desporto. Acrescentar um desporto é escrever um perfil,
não alterar o pipeline.

**1.2 Métricas adimensionais primeiro.**
Cada métrica declara o que exige para ser válida:

| `requires` | Significado | Exemplos |
|---|---|---|
| `none` | Ângulos e rácios normalizados por segmento corporal. Não precisam de calibração nem de cadência alta. | ângulo do joelho, elevação do joelho ÷ comprimento da perna |
| `fps` | Depende de resolução temporal. | tempo de contacto, cadência, tempo de entrega |
| `calibration` | Depende de escala métrica real. | velocidade de largada, altura de largada em metros |

Sempre que exista alternativa adimensional para a mesma pergunta técnica,
preferir essa. Reduz drasticamente a dependência do protocolo de captura.

**1.3 Repetibilidade acima de instantes.**
O ruído da pose 2D num único frame é frequentemente superior ao sinal. Métricas
devem ser calculadas sobre N repetições, com média e variância. Em desportos de
precisão (tiro com arco), a **variância entre repetições é a métrica**, não um
subproduto.

**1.4 Guardar keypoints em bruto, sempre.**
As definições de métrica vão mudar. Se só forem guardados os valores calculados,
todo o histórico fica incomparável a cada afinação de fórmula. Com os keypoints
guardados, recalcula-se o histórico completo. Cada resultado regista a versão da
definição que o produziu.

**1.5 Validade explícita.**
Uma métrica medida fora do plano da câmara está errada por geometria. O relatório
tem de marcar isso, não apresentar o valor com a mesma autoridade dos restantes.

---

## 2. Abstracções centrais

### 2.1 SportProfile

```ts
interface SportProfile {
  id: string;                    // "athletics_running", "cycling_road"
  name: string;
  views: ViewSpec[];
  segmentation: SegmentationSpec;
  poseBackend: PoseBackendSpec;
  objects: ObjectSpec[];         // arco, bicicleta, engenho — vazio se não houver
  metrics: MetricSpec[];
  scoring: ScoringProfile;
  references: ReferenceSet[];
  maturity: 'stable' | 'beta' | 'experimental';
}
```

### 2.2 ViewSpec

```ts
type ViewKind = 'lateral' | 'frontal' | 'posterior' | 'superior' | 'inferior';

interface ViewSpec {
  kind: ViewKind;
  required: boolean;
  // Como interpretar lateralidade nesta vista. Na vista posterior e na
  // inferior o eixo esquerda/direita da imagem inverte-se face à frontal.
  lateralityMapping: 'direct' | 'mirrored';
  // Plano de movimento que esta vista observa sem erro de projecção.
  // Métricas fora deste plano são marcadas como baixa validade.
  observedPlane: 'sagittal' | 'frontal' | 'transverse';
  calibration?: CalibrationSpec;
}
```

### 2.3 CaptureSource

Vídeo e fotografia unificam-se como sequência de frames. Uma fotografia é uma
sequência de comprimento 1.

```ts
interface CaptureSource {
  id: string;
  view: ViewKind;
  mode: 'video' | 'photo' | 'burst';
  frames: FrameRef[];
  fps?: number;                  // ausente em modo photo
  syncGroup?: string;            // ver 2.9
  calibration?: CalibrationResult;
  device: DeviceMetadata;        // modelo, lente, estabilização on/off
  // Obrigatório em modo photo: que evento do ciclo/fase esta imagem representa.
  taggedEvent?: string;
}
```

**Regra do modo fotografia:** duas capturas só podem ser comparadas se tiverem o
mesmo `taggedEvent`. Comparar a elevação do joelho entre duas fotos de fases
diferentes produz uma diferença que nada tem a ver com evolução técnica. O modo
fotografia existe pela praticidade no terreno; onde o evento for difícil de
acertar à mão, vídeo com extracção automática do frame do evento é mais fiável e
deve ser recomendado na interface.

### 2.4 PoseBackend

Adaptador. **MediaPipe Pose é o backend por omissão** (Apache 2.0, corre em CPU
e telemóvel, 33 keypoints incluindo calcanhar e `foot_index`).

```ts
interface PoseBackend {
  id: string;                    // "mediapipe_pose", "custom_swim"
  detect(frames: FrameRef[]): Promise<PoseFrame[]>;
  keypointSchema: KeypointSchema;  // nomes e índices, por backend
}

interface PoseFrame {
  frameIndex: number;
  keypoints: Record<string, { x: number; y: number; z?: number; confidence: number }>;
}
```

O backend é configurável por desporto porque a natação previsivelmente exigirá um
modelo afinado para nadadores em decúbito ventral e submersos, para o qual o
MediaPipe genérico não foi treinado. A camada de métricas nunca acede ao backend
directamente — só ao `KeypointSchema` normalizado.

### 2.5 Filtragem

Camada obrigatória entre pose e cálculo. Não é opcional.

```ts
interface FilterSpec {
  confidenceThreshold: number;   // keypoints abaixo → descartados
  gapInterpolation: 'linear' | 'spline' | 'none';
  maxGapFrames: number;          // acima disto, marcar segmento inválido
  smoothing: { type: 'butterworth'; order: number; cutoffHz: number }
           | { type: 'savitzky_golay'; window: number; polyorder: number }
           | { type: 'none' };
}
```

Butterworth passa-baixo é o padrão em biomecânica. A frequência de corte é
específica do desporto e da cadência do movimento — declarada no perfil, não
global.

### 2.6 Segmentação temporal

A diferença estrutural entre desportos. Três estratégias:

```ts
type SegmentationSpec =
  | { type: 'cyclic'; cycleEvent: string; normalizeTo: 'percent'; phaseVariable?: string }
  | { type: 'phase'; phases: PhaseSpec[]; events: EventSpec[] }
  | { type: 'instant'; events: EventSpec[] };
```

- **`cyclic`** — corrida, ciclismo, natação. O ciclo é normalizado para 0–100%,
  o que permite comparar atletas com cadências diferentes. `phaseVariable`
  permite normalizar por uma variável que não o tempo: no ciclismo, o ângulo da
  manivela (0–360°) é melhor eixo do que o tempo.
- **`phase`** — tiro com arco, lançamentos. Sequência de fases discretas com
  eventos detectáveis a delimitá-las.
- **`instant`** — modo fotografia e análise postural estática.

Todas devolvem `Segment[]`, que é o que o cálculo consome.

### 2.7 MetricSpec

```ts
interface MetricSpec {
  id: string;
  name: string;
  views: ViewKind[];             // vistas necessárias
  keypoints: string[];
  objects?: string[];
  requires: 'none' | 'fps' | 'calibration';
  minFps?: number;
  compute: (ctx: MetricContext) => MetricValue;

  target: | { kind: 'band'; min: number; max: number }      // faixa óptima
          | { kind: 'minimize' }
          | { kind: 'maximize' }
          | { kind: 'match_reference' }
          | { kind: 'consistency' };                        // variância entre repetições

  unit: string;
  bilateral: boolean;            // faz sentido comparar esquerdo vs direito?
  weight: number;                // peso no score, editável pelo treinador
  recommendations: RecommendationTemplate[];  // texto vive junto da métrica
}
```

O texto de recomendação pertence à métrica. Centralizá-lo transformaria o módulo
de relatório num `switch` por desporto.

`bilateral: false` é o caso do tiro com arco, onde a postura é deliberadamente
assimétrica e a simetria não é objectivo.

### 2.8 Objectos

Nenhum modelo de pose deteta um arco, uma bicicleta ou um engenho. Subsistema
paralelo, necessário em três dos cinco desportos iniciais.

```ts
interface ObjectSpec {
  id: string;                    // "bow", "crank", "implement"
  trackedPoints: string[];       // "riser", "upper_limb_tip", "string_nock"
  tracker: 'detector' | 'manual_annotation' | 'assisted';
}
```

`manual_annotation` é um modo de primeira classe, não um fallback: em objectos
rígidos basta anotar num frame e propagar por tracking.

### 2.9 Captura sincronizada e multicâmara

Mesmo começando com uma câmara por vista, o modelo de dados admite várias câmaras
sincronizadas desde o início — senão o 3D fica bloqueado por decisão de schema.

```ts
interface SyncGroup {
  id: string;
  sources: string[];             // CaptureSource ids
  syncMethod: 'audio_clap' | 'visual_flash' | 'timecode' | 'manual';
  syncOffsetFrames: Record<string, number>;
  residualErrorMs?: number;      // qualidade da sincronização
  extrinsics?: CameraExtrinsics[];  // preenchido quando houver calibração 3D
}
```

Triangulação 3D não faz parte da primeira fase, mas as métricas que dela
beneficiam já declaram `observedPlane`, portanto o sistema sabe hoje quais são.

### 2.10 Referências

Nunca um único vídeo. Uma referência é uma **banda** (média ± desvio) sobre
várias execuções.

```ts
interface ReferenceSet {
  id: string;
  kind: 'elite_band' | 'own_baseline' | 'coach_target';
  sport: string;
  event?: string;                // "100m", "recurve_70m"
  samples: number;               // n=1 é assinalado como referência fraca
  bands: Record<string, { mean: number; sd: number }>;
}
```

`own_baseline` é o que serve o caso de o atleta se comparar consigo próprio ao
longo do tempo.

**Nota legal:** vídeo de atletas olímpicos proveniente de transmissões tem
direitos de autor e de imagem. A distribuição de referências pré-carregadas com
esse material exige licenciamento; em alternativa, referências construídas com
atletas consentidos ou carregadas pelo próprio utilizador.

---

## 3. Pipeline

```
CaptureSource(s)
      │
      ▼
  PoseBackend ──────────────► keypoints em bruto ──► PERSISTIDO (§1.4)
      │                              │
      │                    ObjectTracker (paralelo)
      ▼                              │
  Filtragem (§2.5) ◄─────────────────┘
      │
      ▼
  Segmentação (§2.6) ──► Segment[]
      │
      ▼
  Cálculo de métricas (§2.7) ──► MetricValue[] + flags de validade
      │
      ▼
  Comparação (vs ReferenceSet) ──► desvios + classificação
      │
      ▼
  Pontuação (§4) ──► score técnico + score de evolução + confiança
      │
      ▼
  Relatório (texto das próprias métricas) + histórico
```

---

## 4. Pontuação

### 4.1 Dois scores, nunca fundidos

- **Score técnico (0–100)** — proximidade à banda de referência, em absoluto.
- **Score de evolução** — variação face à `own_baseline` do atleta.

Um atleta pode melhorar muito e continuar nos 60. As duas afirmações são
verdadeiras e servem propósitos diferentes; um número único esconde ambas.

### 4.2 Pontuação por métrica

Depende do `target`:

- `band` — 100 dentro da faixa, decaindo com a distância à fronteira mais próxima.
- `minimize` / `maximize` — monótona, saturando nos extremos plausíveis.
- `match_reference` — decai com |desvio| face à média da banda, escalado pelo
  desvio-padrão da referência.
- `consistency` — pontua a variância entre repetições, não o valor.

**Não usar diferença percentual sobre valores que podem aproximar-se de zero**
(queda da anca, desvio lateral). A divisão explode. Usar desvio absoluto com
limiar próprio, ou desvios-padrão da banda de referência.

### 4.3 Classificação

Verde < 5% · Amarelo 5–15% · Vermelho > 15%, onde a percentagem é expressa em
fracção do intervalo aceitável da métrica, não em fracção do valor da referência.

### 4.4 Confiança

Todo o score é acompanhado de um indicador de qualidade dos dados: confiança
média da pose, fps efectivo, presença de calibração, e quantas repetições
sustentam o valor. 87 obtido de um vídeo a 30 fps sem calibração não é o mesmo
que 87 obtido a 240 fps calibrado.

### 4.5 Precisão aparente

Apresentar em bandas de 5 pontos ou com margem explícita. `87,3` sugere uma
exactidão que a pose 2D não tem.

### 4.6 Pesos

Os pesos são juízo de treinador, não constante universal. Definidos por perfil,
visíveis e editáveis na interface. Os valores nos perfis de desporto são pontos
de partida a validar com treinadores, não verdades estabelecidas.

---

## 5. Modelo de dados

```
Athlete
  └── Session (data, desporto, condições, notas)
        ├── CaptureSource[]        (vídeos/fotos + metadados de dispositivo)
        ├── SyncGroup?
        ├── PoseData[]             ← keypoints em bruto, retidos permanentemente
        ├── ObjectData[]
        ├── MetricResult[]         (valor, validade, versão da definição)
        ├── Score                  (técnico, evolução, confiança)
        └── Report
```

`MetricResult` regista `metricDefinitionVersion`. Quando uma fórmula muda, o
histórico é recalculado a partir de `PoseData` e não se perde comparabilidade.

---

## 6. Desportos e ordem de implementação

| Desporto | Perfil | Dificuldade | Maturidade alvo |
|---|---|---|---|
| Ciclismo | [`ciclismo.md`](sports/ciclismo.md) | Baixa | `stable` |
| Atletismo — corrida | [`atletismo-corrida.md`](sports/atletismo-corrida.md) | Baixa/média | `stable` |
| Tiro com arco | [`tiro-com-arco.md`](sports/tiro-com-arco.md) | Média/alta | `beta` |
| Natação | [`natacao.md`](sports/natacao.md) | Alta | `beta` |
| Lançamentos | [`lancamentos.md`](sports/lancamentos.md) | Alta | `experimental` |

Ordem sugerida: **ciclismo primeiro** — câmara fixa, atleta em rolo, movimento
planar e perpendicular à câmara, iluminação controlada. É o ambiente mais
favorável para validar todo o pipeline antes de enfrentar rotação, água e
oclusão. Cobre também o caso estático (o bike fit é análise postural parada), o
que exercita o modo `instant` desde o início.

---

## 7. Estrutura de repositório proposta

```
docs/
  ARCHITECTURE.md
  CAPTURE.md
  sports/                  perfis por desporto
core/
  pose/                    adaptadores de backend
  filtering/
  segmentation/            cyclic | phase | instant
  metrics/                 primitivas (ângulos, distâncias normalizadas)
  objects/                 tracking
  comparison/
  scoring/
  reporting/
sports/                    perfis executáveis (um módulo por desporto)
```

A regra que mantém a estrutura honesta: **nada em `core/` importa de `sports/`.**
Se for preciso, é sinal de que falta uma abstracção.
