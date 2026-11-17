# JARVIS LifeOS

JARVIS LifeOS é uma camada sobre o OpenJarvis que transforma o assistente em
um sistema pessoal de inteligência e execução: agente central com
personalidade, memória persistente em camadas, organização da vida (metas,
projetos, tarefas, hábitos, compromissos, decisões), revisões periódicas,
autonomia por nível de risco e auditoria de cada ação.

Tudo roda localmente. Os dados ficam em um único arquivo SQLite sob
`~/.openjarvis/lifeos/` (ou `%USERPROFILE%\.openjarvis\lifeos\` no Windows;
respeita `OPENJARVIS_HOME`).

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

### Painel web

```bash
jarvis serve        # depois abra http://127.0.0.1:8000/lifeos
```

Painel, conversa com histórico, tarefas, metas e projetos, hábitos, memória,
revisões, autonomia/pendências e auditoria. Se `server.api_key` estiver
definido, informe a chave na aba **Conexão**.

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
| 2 assistido (padrão) | toda ação com efeito pede autorização |
| 3 autorizado | categorias pré-autorizadas executam sozinhas |
| 4 proativo | como 3; o JARVIS monitora objetivos e propõe iniciativas |

Regras fixas, independentes do nível:

- risco **alto** (enviar mensagens, excluir dados, alterar configuração,
  executar código) sempre pede confirmação e não pode ser pré-autorizado;
- risco **crítico** (compras, pagamentos, movimentações financeiras) sempre
  exige confirmação explícita e não pode ser pré-autorizado;
- ferramentas sem classificação são tratadas como risco alto.

Quando não há terminal interativo (painel web, `jarvis ask`), a ação fica
**pendente**. Aprovar uma pendência de ferramenta LifeOS a executa na hora;
para outras ferramentas, a aprovação vale uma única vez para a chamada
idêntica.

O callback genérico de confirmação do OpenJarvis (`jarvis ask` aprova tudo
automaticamente) **não** é usado pela política do LifeOS.

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
autonomy_level = 2           # valor inicial; `autonomy set` grava no banco e prevalece
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

Prefixo `/v1/lifeos` (protegido por `server.api_key` quando definido):
`status`, `memory`, `items/{kind}`, `tasks/{id}/done`, `habits/{id}/log`,
`alerts`, `reviews`, `reviews/{kind}`, `autonomy`, `grants/{category}`,
`approvals`, `approvals/{id}/approve|deny`, `audit`, `sessions`, `chat`.
Documentação interativa em `/docs` quando `jarvis serve` está ativo.

## Arquitetura

Veja [JARVIS LifeOS — arquitetura](../architecture/lifeos.md).
