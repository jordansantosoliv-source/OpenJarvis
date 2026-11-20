# ARQUIVO 013 — PROGRESSO

Canal BR de crimes reais/mistérios em animação 2D noir. Vídeos verticais 9:16, 65–90 s.
Paleta: grafite, vermelho escuro (#7A1F1F), papel envelhecido (#E8DCC0). Personagem fictício: Agente 013.

## Estado (2026-11-20)
- **EP01 "Máscaras de Chumbo" (Niterói, 1966): CONCLUÍDO.** Entregue ao usuário em 2 versões:
  `ARQUIVO013_EP01_mascaras_de_chumbo.mp4` (86 s, sem voz) e `..._narrado.mp4` (84,5 s, voz IA).
  QA (video-tools `qa_report`, alvo tiktok): tudo OK; -13,9 LUFS, TP -1,3 dB, 1080×1920, 30 fps, 59 MB.
- Os MP4 não estão no git (60 MB cada). Recriar: `pipeline/build.sh ep01` (~3 min, 4 núcleos).
- Pipeline com cache validado: refaz a timeline aprovada com diferença ≤10 ms (cena) e ≤1 ms (legenda);
  quadros iguais aos aprovados (dif. média ≤0,3/255).

## Arquivos
```
arquivo013/
  PROGRESSO.md            este arquivo
  package.json(+lock)     fontes @fontsource (Bebas Neue, Oswald, Courier Prime, Special Elite)
  pipeline/
    setup.sh              instala tudo (idempotente)
    build.sh              <ep> [vo|audio|frames|preview|mux|all]
    retime.py             voz Piper + cache + seleção Whisper; gera build/timeline.json e vo.wav
    audio.py              trilha/ambiência/efeitos sintetizados (sem licença de terceiros)
    render.js             quadros via Playwright (modos range|preview|scenes)
    gen_textures.py       grain.png / paper.png (seed fixa, determinístico)
  ep01/
    scene.html, scenes.js arte SVG das 11 cenas (específica do caso)
    timeline_v1.json      BASE: cenas, legendas, selos, efeitos (editar aqui)
    narration.json        texto FALADO por cena (1 linha por legenda)
    timeline_final.json   timeline aprovada do vídeo narrado (referência)
    vo_cache/             32 falas aprovadas (wav) + manifest.json  <- não regenerar
    original/             scripts v1 (só referência)
    build/                (ignorado) saídas: timeline.json, vo.wav, audio.wav, mix.wav, frames/
  entrega/                (ignorado) MP4 finais, nome com data-hora (nunca sobrescreve)
```

## Como rodar
```
cd arquivo013 && pipeline/setup.sh
pipeline/build.sh ep01 preview     # 1 quadro/cena -> ep01/build/preview_sheet.jpg (barato)
pipeline/build.sh ep01             # vídeo completo -> entrega/
SCENES=s3,s7 pipeline/build.sh ep01 frames   # só cenas alteradas (se durações não mudaram)
```
Mudou texto falado → só as falas novas são sintetizadas (4 tomadas, Whisper escolhe; `<-- OUVIR` se < 0,99).
Mudou duração de cena → rodar `frames` completo (quadros deslocam).

## Decisões
- Caso escolhido por ser real, documentado, sem violência gráfica e sem suspeito acusado.
- Vítimas só de costas/silhueta; corpos nunca mostrados; selos "RECONSTRUÇÃO ARTÍSTICA" nas cenas dramatizadas;
  "Agente 013 é personagem fictício" na cena 2; bilhete rotulado "TRANSCRIÇÃO • VERSÃO MAIS DIVULGADA".
- Arte própria em SVG desenhado em código (sem gerador de imagem); trilha sintetizada (sem direitos autorais).
- Legendas na área segura (x 70–930, base em y 1490); texto da legenda = roteiro escrito.
- Voz: Piper `pt_BR-faber-medium`, length_scale 1.0 (0,95 se a tomada for melhor), noise .5/.6.
  Pós: EQ + compressor + eco leve; trilha a 80% com ducking (sidechain) sob a voz; loudnorm 2 passadas -14 LUFS.
- Pronúncia corrigida no texto falado (legenda mantém grafia correta):
  "em Niterói" (sozinho soava "Neterer"); "Goitacazes" (legenda: Goytacazes); "De terno. De capa de chuva.";
  "Este é o Arquivo zero treze."; "Depois, eles subiram o Morro do Vintém."; "Agosto de sessenta e seis".
- Vídeo: H.264 CRF 22, maxrate 9M (60 MB/85 s); última cena +1,6 s para o logo.

## Dossiê EP01 (pesquisa concluída — não repetir)
Acesso: só trechos via busca web. Páginas completas não abertas (WebFetch falha por DNS mesmo com domínio liberado).
- ✅ Corpos achados em ago/1966 no Morro do Vintém, Niterói (20/08 mais citado; algumas fontes: 21/08).
- ✅ Manoel Pereira da Cruz e Miguel José Viana, técnicos em eletrônica, de Campos dos Goytacazes; chegaram a Niterói em 17/08.
- ✅ Compraram capas de chuva e garrafa de água; achados de terno e capa; máscaras de chumbo rudimentares; sem sinais de violência.
- ✅ Bilhete (versão mais divulgada): "16:30 estar no local determinado. 18:30 ingerir cápsula, após efeito proteger metais aguardar sinal máscara".
- ✅ Causa das mortes nunca determinada. ✅ Gracinda Barbosa Coutinho de Souza relatou objeto laranja na noite de 17/08 (JB 24/08/1966, via fonte secundária).
- ⚠️ Divergem: idades (32/34), toxicologia (não feita / órgãos decompostos / nada encontrado), dinheiro, caso Hermes 1962, frase do delegado.
- ⚠️ Amigo Elcio Gomes: "espiritualistas científicos" (usado com atribuição "segundo depoimento").
- Fontes: pt.wikipedia.org/wiki/Mistério_das_máscaras_de_chumbo · en.wikipedia.org/wiki/Lead_masks_case ·
  skeptoid.com/episodes/398 · aventurasnahistoria.com.br/noticias/reportagem/o-caso-das-mascaras-de-chumbo.phtml ·
  thetvdb.com/series/linha-direta-justica/episodes/9504578 · memoria.bn.gov.br (JB ago/1966, não acessado).

## Problemas conhecidos
- Fontes completas ainda não conferidas: usuário deve abrir Wikipedia PT e Skeptoid antes de publicar.
- Whisper ouviu "Movo do Vintém" em 1 tomada: ouvir 0:20–0:24 do narrado.
- WebFetch não resolve DNS de nenhum site nesta conta; usar WebSearch (trechos) e declarar o limite.
- Rede do ambiente "jordan" liberada: Wikipedia PT/EN, skeptoid.com, pmig96.wordpress.com,
  huggingface.co, cdn-lfs.hf.co, cdn-lfs-us-1.hf.co, cas-bridge.xethub.hf.co, us.aws.cdn.hf.co.
  Whisper: usar `HF_HUB_DISABLE_XET=1` (cas-server.xethub.hf.co não liberado).
- faster-whisper + av: passar áudio como array numpy (decode por arquivo quebra).

## Economia de tokens/tempo (regras)
- Não ler MP4 nem quadros inteiros: usar `qa_report` (metadados) e `preview_sheet.jpg` (270 px/cena).
- Não reabrir scenes.js inteiro: buscar a função da cena com grep (`function s7`) e editar só ela.
- Logs: só resumos (render imprime JSON curto; retime só falas novas).
- Reusar vo_cache, voices/, node_modules/, texturas; não refazer pesquisa do dossiê.
- Tarefas pequenas: uma cena, uma fala ou uma etapa do build por vez.

## Próxima tarefa
1. Usuário: assistir EP01 narrado, conferir fontes, publicar (título/descrição/hashtags na conversa de origem).
2. EP02: escolher novo caso real e verificar fontes suficientes (pesquisa nova, registrar dossiê aqui).
3. Otimização opcional: extrair de ep01/scenes.js uma biblioteca comum (Agente 013, arquivo, carimbos, legendas)
   para que cada episódio só escreva as cenas novas.
