# JARVIS LifeOS

JARVIS LifeOS é uma camada sobre o OpenJarvis que transforma o assistente em
um sistema pessoal de inteligência e execução: agente central com
personalidade, memória persistente em camadas, organização da vida (metas,
projetos, tarefas, hábitos, compromissos, decisões), revisões periódicas,
autonomia por nível de risco e auditoria de cada ação.

Tudo roda localmente, numa pasta exclusiva (`%USERPROFILE%\JARVIS-LifeOS`
no Windows; altere com a variável `JARVIS_LIFEOS_HOME`):

```
JARVIS-LifeOS/
├── config/      lifeos.toml, persona.md
├── memory/      lifeos.db (SQLite)
├── workspace/   arquivos que o JARVIS pode organizar
├── research/    pesquisas
├── reports/     revisões arquivadas (Markdown)
├── logs/        cópia do registro de ações (JSONL)
├── backups/     backups com data e hora
└── interface/   reservado para a interface
```

O `config.toml` do OpenJarvis nunca é escrito pelo LifeOS; ele só é lido
(e copiado) pelo comando `jarvis lifeos backup`.

### Permissões por pasta

A ferramenta de arquivos do JARVIS (`lifeos_files`) só enxerga
`JARVIS-LifeOS`. Caminhos absolutos, `..` e links simbólicos que saem da
pasta são recusados. Cada pasta tem uma permissão em `[folders]` no
`lifeos.toml`:

| Pasta | Padrão |
|-------|--------|
| config, logs, interface | `read` |
| workspace, research, reports | `write` |
| memory, backups | `none` |

Criar, anexar e mover dentro de pastas `write` é organização (sem
confirmação no nível 3). Sobrescrever ou excluir sempre pede confirmação.
As ferramentas nativas `file_write` e `apply_patch`, que não ficam
confinadas à pasta, são classificadas como risco alto.

## Estado atual

| Fase | Conteúdo | Estado |
|------|----------|--------|
| 1 — Fundação | agente central, persona, memória em camadas, LifeOS, autonomia, auditoria, CLI, API, painel | **implementada e testada** |
| 2 — Inteligência | agentes especializados, delegação, memória episódica automática | planejada |
| 3 — Organização | ciclos de revisão guiados, indicadores, histórico de decisões avançado | parcial (revisões e alertas já existem) |
| 4 — Automações | agendamento das revisões, notificações (Telegram), Google, arquivos | planejada |
| 5 — Evolução | avaliação dos agentes, otimização | planejada |

## Instalação (Windows)

Pré-requisitos: Python 3.11–3.13 e um motor de inferência local (Ollama é o
padrão do OpenJarvis).

```powershell
irm https://open-jarvis.github.io/OpenJarvis/install.ps1 | iex   # instala o OpenJarvis
```

Ou, a partir deste repositório:

```powershell
git clone <seu-fork> OpenJarvis
cd OpenJarvis
uv sync --extra server
uv run jarvis lifeos init
```

`jarvis lifeos init` cria:

- `lifeos.toml` — configuração do LifeOS (separada do `config.toml`);
- `persona.md` — personalidade do JARVIS, editável;
- `lifeos.db` — banco local.

O modelo de linguagem é o configurado no OpenJarvis (`jarvis init`,
`jarvis model`). O LifeOS não escolhe modelo: a escolha depende do seu
hardware. Para chamadas de ferramenta confiáveis, use um modelo com suporte a
function calling.

## Uso

### Conversa

```bash
jarvis lifeos chat                 # interativo; pede autorização no terminal
jarvis lifeos chat -q "Qual meu plano para hoje?"
jarvis lifeos chat --session <id>  # retoma conversa
jarvis ask -a jarvis_orchestrator "..."   # via comando nativo (ações de risco ficam pendentes)
```

### Central de comando (interface)

```bash
jarvis serve        # depois abra http://127.0.0.1:8000/lifeos
```

Interface holográfica (azul-marinho, ciano e azul elétrico), em HTML/CSS/JS
sem dependências externas, servida pelo próprio servidor:

- **centro:** núcleo do JARVIS com estados reais: ONLINE, PROCESSANDO
  (durante a chamada ao modelo), ESCUTANDO (gravando o microfone),
  RESPONDENDO (reproduzindo voz), FALHA/OFFLINE;
- **esquerda:** módulos (tarefas, metas/projetos, hábitos, revisões,
  memória, arquivos, autonomia, auditoria), plano do dia, aprovações
  pendentes, projetos e ferramentas;
- **direita:** CPU e RAM reais (`psutil`), estado do modelo e modelos
  carregados no Ollama (`/api/ps`), memória, alertas, atividades e logs;
- **inferior:** histórico de conversas, texto, voz.

Voz usa os endpoints existentes do OpenJarvis: `/v1/speech/transcribe`
(entrada) e `/v1/speech/synthesize` (saída). Os botões ficam desativados
quando o servidor não tem backend de voz configurado. O reconhecimento de
voz do navegador não é usado porque envia áudio para a nuvem.

Se o servidor exigir chave de API (variável `OPENJARVIS_API_KEY` ou
`[server.auth] api_key` no `config.toml`), informe a chave no botão ⚙.

### Organização

```bash
jarvis lifeos add goal title="Melhorar desempenho acadêmico" horizon=medium
jarvis lifeos add project title="Cálculo I" goal_id=1
jarvis lifeos add task title="Lista 3" project_id=1 priority=1 due_date=2026-11-20
jarvis lifeos list task --status todo,doing
jarvis lifeos update task 1 status=doing
jarvis lifeos done 1
jarvis lifeos add habit title="Ler 20 minutos" cadence=daily
jarvis lifeos habit-log 1
jarvis lifeos add commitment title="Dentista" starts_at="2026-11-18 10:00" ends_at="2026-11-18 11:00"
jarvis lifeos add decision title="Trocar de curso?" options="A, B" decision="Adiar" review_date=2027-01-15
jarvis lifeos plan "Física — prova" "Revisar cinemática" "Lista 4" "Simulado" --goal 1 --start 2026-11-18 --every 2
```

Prioridade: 1 (máxima) a 4. Horizonte de metas: `short`, `medium`, `long`.

### Revisões e alertas

```bash
jarvis lifeos review morning
jarvis lifeos review evening --notes "Internet caiu à tarde" --save
jarvis lifeos review weekly --save
jarvis lifeos review monthly
jarvis lifeos alerts
```

Alertas detectados: tarefas atrasadas, prazos próximos, projetos com prazo
vencido, projetos sem progresso, metas sem projeto ativo, hábitos
inconsistentes, conflitos de agenda, dias acima da capacidade e decisões com
revisão vencida. A quantidade é limitada (`review.max_alerts`) para não gerar
ruído. O plano do dia nunca excede `review.daily_task_capacity`.

### Memória

```bash
jarvis lifeos memory add "Prefere estudar à noite"
jarvis lifeos memory add "Acorda às 6h" --subject usuario.acordar
jarvis lifeos memory add "Acorda às 7h" --subject usuario.acordar --replace
jarvis lifeos memory add "Responder sempre em português" --layer identity
jarvis lifeos memory add "Talvez prefira treinar cedo" --hypothesis
jarvis lifeos memory search "estudo"
jarvis lifeos memory correct 3 --content "..."
jarvis lifeos memory history 3
jarvis lifeos memory forget 3
```

| Camada | Uso |
|--------|-----|
| `identity` | regras de comportamento do JARVIS (entram em todo prompt) |
| `personal` | fatos fornecidos pelo usuário |
| `episodic` | decisões, problemas, soluções, eventos |
| `operational` | estado atual relevante |
| `knowledge` | notas, pesquisas, referências |

Garantias:

- persistência entre reinicializações (SQLite com WAL);
- busca textual FTS5/BM25 com remoção de acentos;
- busca semântica opcional (embeddings via Ollama, fusão RRF com a textual);
- deduplicação por texto normalizado;
- correções criam nova versão, com histórico;
- `subject` impede contradições silenciosas: conteúdo diferente para o mesmo
  assunto exige `--replace`;
- separação entre `confirmed` e `hypothesis`;
- exclusão definitiva inclui o histórico.

Para ativar a busca semântica, escolha um modelo de embeddings compatível com
seu hardware, por exemplo `ollama pull nomic-embed-text`, e defina em
`lifeos.toml`:

```toml
[semantic]
enabled = true
model = "nomic-embed-text"
```

Depois: `jarvis lifeos memory reindex`.

### Autonomia

```bash
jarvis lifeos autonomy show
jarvis lifeos autonomy set 3
jarvis lifeos autonomy grant planning_write
jarvis lifeos autonomy revoke planning_write
jarvis lifeos approvals list
jarvis lifeos approvals approve <id>
jarvis lifeos approvals deny <id>
```

| Nível | Comportamento |
|-------|---------------|
| 1 consultivo | só leitura; o JARVIS recomenda, não executa |
| 2 assistido | toda ação com efeito pede autorização |
| 3 autorizado (padrão) | categorias pré-autorizadas executam sozinhas |
| 4 proativo | como 3; o JARVIS monitora objetivos e propõe iniciativas |

Pré-autorizado por padrão: `report` (relatórios), `file_organize`
(organização dentro das pastas permitidas) e `external_request` (pesquisas
somente leitura, como busca na web). Consultas e análises são leitura e
nunca pedem confirmação.

Regras fixas, independentes do nível:

- risco **alto** (enviar mensagens, excluir dados, modificar documentos
  existentes, operações externas sensíveis como `http_request`, alterar
  configuração, executar código) sempre pede confirmação e não pode ser
  pré-autorizado;
- risco **crítico** (compras, pagamentos, movimentações financeiras) sempre
  exige confirmação explícita e não pode ser pré-autorizado;
- ferramentas sem classificação são tratadas como risco alto.

Quando não há terminal interativo (painel web, `jarvis ask`), a ação fica
**pendente**. Aprovar uma pendência de ferramenta LifeOS a executa na hora;
para outras ferramentas, a aprovação vale uma única vez para a chamada
idêntica.

O callback genérico de confirmação do OpenJarvis (`jarvis ask` aprova tudo
automaticamente) **não** é usado pela política do LifeOS.

### Backups

```bash
jarvis lifeos backup --label antes-da-mudanca
```

Copia, para `backups/AAAAMMDD-HHMMSS-rotulo/`: o banco (cópia consistente
pela API de backup do SQLite), `lifeos.toml`, `persona.md` e o
`config.toml` do OpenJarvis (como `openjarvis-config.toml`). Os originais
só são lidos. `jarvis lifeos wipe` faz um backup automático antes de apagar.

### Arquivos

```bash
jarvis lifeos files              # pastas e permissões
jarvis lifeos files workspace    # conteúdo
```

### Auditoria e dados

```bash
jarvis lifeos audit
jarvis lifeos audit --verify          # verifica a cadeia de hashes SHA-256
jarvis lifeos export dados.json
jarvis lifeos wipe                    # apaga dados pessoais (mantém auditoria)
jarvis lifeos wipe --include-audit
```

Cada decisão de política e cada resultado de ferramenta é registrado com
categoria, risco, nível, parâmetros e resultado. Cada registro guarda o hash
do anterior; alterar ou apagar um registro passado é detectado.

### Persona

```bash
jarvis lifeos persona show
jarvis lifeos persona path    # edite este arquivo
jarvis lifeos persona reset   # restaura o padrão (cria .bak)
```

## Configuração (`lifeos.toml`)

```toml
language = "pt-BR"
user_name = ""
autonomy_level = 3           # valor inicial; `autonomy set` grava no banco e prevalece
memory_context_limit = 8

[semantic]
enabled = false
provider = "ollama"
model = "nomic-embed-text"
base_url = "http://localhost:11434"

[review]
daily_task_capacity = 5
due_soon_days = 3
stale_project_days = 14
habit_min_rate = 0.5
max_alerts = 7
```

Chaves desconhecidas geram erro (evita erros de digitação silenciosos).

## API HTTP

Prefixo `/v1/lifeos`: `status`, `system`, `files`, `backup`, `memory`,
`items/{kind}`, `tasks/{id}/done`, `habits/{id}/log`, `alerts`, `reviews`,
`reviews/{kind}`, `autonomy`, `grants/{category}`, `approvals`,
`approvals/{id}/approve|deny`, `audit`, `sessions`, `chat`.
Documentação interativa em `/docs` quando `jarvis serve` está ativo.

### Chave de API

Quando `OPENJARVIS_API_KEY` (ou `[server.auth] api_key` no `config.toml`)
está definida, todas as rotas `/v1/*` exigem `Authorization: Bearer <chave>`.

### Proteção contra requisições forjadas (CSRF) e DNS rebinding

Vale para `/lifeos` e `/v1/lifeos/*`, com ou sem chave de API:

1. **Host local.** O cabeçalho `Host` precisa ser `localhost`, `127.0.0.1`
   ou `::1`. Para acessar pela rede local, libere nomes explicitamente em
   `JARVIS_LIFEOS_ALLOWED_HOSTS` (separados por vírgula).
2. **Cabeçalho obrigatório em alterações.** POST, PUT, PATCH e DELETE
   exigem `X-JARVIS-LifeOS: 1`. A central de comando envia automaticamente;
   scripts precisam enviar também, por exemplo:

   ```powershell
   Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/lifeos/backup -Headers @{ "X-JARVIS-LifeOS" = "1" }
   ```

3. **Origem conferida.** Pedidos com `Origin` diferente do servidor,
   `Origin: null` ou `Sec-Fetch-Site: cross-site` são recusados com `403`.

Leituras (GET) não exigem o cabeçalho, mas seguem a regra de Host. As rotas
do próprio OpenJarvis não são afetadas; para elas, a defesa é definir
`OPENJARVIS_API_KEY`.

## Arquitetura

Veja [JARVIS LifeOS — arquitetura](../architecture/lifeos.md).
