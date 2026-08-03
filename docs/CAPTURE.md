# Protocolo de captura

Nenhum detector de pose corrige um vídeo mal capturado. A qualidade dos dados
determina-se aqui, não no software.

Dispositivo de referência: **iPhone 17 Pro**. As definições abaixo aplicam-se a
qualquer telemóvel recente; os nomes das opções variam.

---

## 1. Definições de câmara

### 1.1 Desligar obrigatoriamente

| Definição | Porquê |
|---|---|
| **Modo Cinema / Cinematic** | Aplica desfoque de profundidade sintético. Suaviza contornos de membros e degrada a deteção de keypoints, sobretudo nas extremidades (pés, mãos). |
| **Estabilização (OIS/EIS)** | A estabilização electrónica corta e deforma cada frame de forma independente. Numa câmara fixa isto destrói a geometria entre frames e invalida a calibração. É o erro mais grave e o menos óbvio. |
| **Troca automática de lente** | Se o telemóvel alternar entre principal e ultra-grande-angular a meio da gravação, os parâmetros intrínsecos mudam e a calibração deixa de ser válida. Fixar a lente antes de gravar. |

### 1.2 Bloquear

- **Exposição, foco e balanço de brancos.** O ajuste automático provoca variações
  de luminosidade e *focus breathing* que introduzem ruído na deteção.

### 1.3 Lente

Usar a **lente principal**. A ultra-grande-angular tem distorção radial forte que
enviesa ângulos na periferia do enquadramento; só é utilizável com correcção de
distorção aplicada previamente.

### 1.4 Cadência de captura

| Análise | Mínimo | Recomendado |
|---|---|---|
| Postura estática, bike fit | 30 fps | 60 fps |
| Ângulos articulares em movimento cíclico | 60 fps | 120 fps |
| Tempo de contacto no solo, tipo de apoio do pé | 120 fps | 240 fps |
| Largada em lançamentos | 240 fps | mais, se disponível |

Referência: um contacto no solo em corrida de elite dura cerca de 80–120 ms. A
30 fps são 3–4 frames — margem de erro inaceitável. A 240 fps são 20–30 frames.

Confirmar no dispositivo que combinação de resolução e cadência está disponível;
as cadências mais altas costumam exigir resolução mais baixa, e 1080p a alta
cadência é preferível a 4K a baixa cadência para tudo o que seja temporal.

### 1.5 Obturador e luz

Desfoque de movimento apaga as extremidades, que são precisamente os keypoints
menos estáveis. Obturador rápido — como ordem de grandeza, não mais lento que
1/(2 × fps), e tão rápido quanto a luz permitir. Isto exige luz abundante:
exterior com sol, ou iluminação artificial adequada em pavilhão e piscina.

### 1.6 Formato

Gravar em Rec.709 (HEVC/H.264). Log e ProRes não trazem benefício para deteção
de pose e acrescentam um passo de conversão que pode introduzir inconsistências
entre capturas.

### 1.7 Rolling shutter

Os sensores CMOS lêem a imagem linha a linha, o que inclina objectos em
movimento lateral rápido. Atenua-se com cadências altas e obturador rápido, mas
não desaparece — é mais uma razão para preferir métricas angulares no plano da
câmara a medições de posição absoluta em movimentos muito rápidos.

---

## 2. Posicionamento

- **Tripé.** Sem excepção. Câmara na mão invalida a comparação entre sessões.
- **Perpendicular ao plano de movimento.** Um desvio angular da câmara introduz
  erro de projecção em todos os ângulos medidos, e esse erro não é detectável a
  partir do vídeo.
- **Altura da câmara à altura da zona de interesse** (anca, para análise de
  membros inferiores), para minimizar paralaxe.
- **Distância registada e repetida** entre sessões. Anotar nos metadados.
- **Zona de análise marcada no solo**, para que o atleta seja sempre analisado no
  mesmo ponto do enquadramento — a distorção de lente varia com a posição na
  imagem.

---

## 3. Calibração

Colocar no enquadramento, no **plano de movimento do atleta**, um objecto de
comprimento conhecido (régua, fita marcada, cone com altura conhecida). É isto
que converte píxeis em centímetros.

Sem calibração continuam válidas todas as métricas `requires: 'none'` — ângulos
e rácios normalizados por segmento corporal. É por isso que a arquitectura
privilegia métricas adimensionais: funcionam com captura de campo simples.

Casos especiais:

- **Piscina** — as marcações do fundo e as balizas de raia têm dimensões
  regulamentares conhecidas e servem de calibração permanente.
- **Câmara submersa** — a porta da caixa estanque refracta. Calibrar debaixo de
  água, com padrão de xadrez ou ChArUco submerso; a calibração feita em ar não é
  válida em água.
- **Multicâmara 3D** — exige um alvo de calibração visível simultaneamente por
  todas as câmaras.

---

## 4. Multicâmara

### 4.1 Sincronização

Necessária sempre que duas vistas sejam usadas na mesma análise.

| Método | Precisão | Notas |
|---|---|---|
| Timecode (hardware dedicado) | sub-frame | Melhor opção; requer equipamento. |
| Palma sonora + flash visual | ~1 frame | Prático e suficiente na maioria dos casos. Alinhar pela forma de onda áudio. |
| Alinhamento manual por evento | 1–3 frames | Último recurso. |

Precisão necessária: a 240 fps um frame são ~4 ms. Para medir um tempo de
contacto de ~100 ms, um erro de sincronização de vários frames é significativo.
O `SyncGroup` regista o erro residual estimado, e o relatório usa-o para marcar a
confiança das métricas que dependem de duas vistas.

### 4.2 Procedimento

1. Iniciar a gravação em todas as câmaras.
2. Executar o evento de sincronização (palma seca + flash) dentro do campo de
   visão e de captação áudio de todas.
3. Executar o gesto técnico.
4. Repetir o evento de sincronização no fim, para detectar deriva de relógio
   entre dispositivos ao longo de gravações longas.

---

## 5. Metadados obrigatórios por captura

Atleta · desporto e prova · data · vista · modelo de dispositivo e lente · fps ·
resolução · estabilização (deve ler `off`) · distância e altura da câmara ·
presença e tipo de calibração · condições (piso, vento, luz, temperatura da água)
· em modo fotografia, o evento etiquetado.

Sem estes campos a comparação entre sessões não é defensável.

---

## 6. Lista de verificação rápida

- [ ] Tripé montado, câmara perpendicular ao plano de movimento
- [ ] Modo Cinema desligado
- [ ] Estabilização desligada
- [ ] Lente principal fixada
- [ ] Exposição, foco e balanço de brancos bloqueados
- [ ] Cadência adequada à análise (ver 1.4)
- [ ] Objecto de calibração no plano do atleta
- [ ] Zona de análise marcada no solo
- [ ] Multicâmara: evento de sincronização no início e no fim
- [ ] Metadados registados
