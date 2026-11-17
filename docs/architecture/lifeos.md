# JARVIS LifeOS — diagnóstico e arquitetura

## 1. Diagnóstico do OpenJarvis (base: commit `a7a4355`)

OpenJarvis é um framework Python (≈180 mil linhas em `src/openjarvis`) para
IA pessoal local. Componentes relevantes:

| Área | Onde | O que oferece |
|------|------|---------------|
| Registros | `core/registry.py` | `AgentRegistry`, `ToolRegistry`, etc. Descoberta por decorador |
| Agentes | `agents/` | `BaseAgent`, `ToolUsingAgent`, `orchestrator` (loop de function calling com gancho de governança `_check_tool_allowed`), `operative`, `monitor_operative`, `proactive_agent`, `morning_digest`, `deep_research` |
| Ferramentas | `tools/` | `BaseTool`/`ToolSpec`/`ToolExecutor` com RBAC, taint tracking, scanner de prompt injection, timeout, loop guard |
| Memória | `memory/` | fatos extraídos automaticamente (`facts.json`, camada única, com níveis de confiança) |
| Memória documental | `tools/storage/` | SQLite/FTS5, BM25, FAISS, ColBERT, embeddings (Ollama, sentence-transformers) |
| Persona | `prompt/builder.py` | `SOUL.md`, `MEMORY.md`, `USER.md` |
| Aprovações | `tools/approval_store.py` | pendências do agente proativo (SQLite) |
| Agendador | `scheduler/` | tarefas cron/intervalo persistentes |
| Segurança | `security/` | política de capacidades, auditoria SecurityEvent com cadeia Merkle, SSRF, guardrails |
| Canais | `channels/` | Telegram, e-mail, WhatsApp, Slack, etc. |
| Conectores | `connectors/` | Gmail, Calendar, Drive, Tasks (OAuth) |
| Servidor | `server/` | FastAPI compatível com OpenAI + rotas próprias |
| Interface | `frontend/` | React/Vite/Tauri (app desktop) |
| CLI | `cli/` | `jarvis ask/chat/serve/...` (Click) |

### Limitações encontradas

- Memória de fatos tem uma camada só, sem histórico de versões, sem chave de
  assunto, sem distinção fato/hipótese explícita para o usuário.
- Não existe modelo de domínio para metas, projetos, tarefas e hábitos.
- `jarvis ask` liga `confirm_callback=lambda _: True`: ferramentas com
  `requires_confirmation` são aprovadas automaticamente.
- Não há conceito de nível de autonomia por risco.
- A auditoria de segurança registra eventos de segurança, não decisões de
  negócio do agente.
- 79 testes já falham na base (ambiente: browser, recuperação, loop guard,
  etc.). Nenhuma falha nova foi introduzida pelo LifeOS.

## 2. Recursos reutilizados (sem duplicação)

| Necessidade | Reuso |
|-------------|-------|
| Loop de raciocínio com ferramentas | `OrchestratorAgent` (subclasse) |
| Segurança das ferramentas | `ToolExecutor` (RBAC, taint, injection scanner, timeout) |
| Registro de componentes | `AgentRegistry`, `ToolRegistry` |
| Motores e modelos | `engine.get_engine`, configuração do OpenJarvis |
| Embeddings | `tools/storage/embeddings.OllamaEmbedder` |
| Persona do usuário | `SystemPromptBuilder.persona_sections()` (USER/SOUL/MEMORY) anexado |
| Servidor/autenticação | `server/app.create_app` + middleware de API key |
| Caminhos | `core/paths.get_config_dir` (respeita `OPENJARVIS_HOME`) |

## 3. Arquitetura do JARVIS LifeOS

```
             CLI (jarvis lifeos)   Painel /lifeos   API /v1/lifeos   jarvis ask -a jarvis_orchestrator
                      \                  |                 |                    /
                       +---------- JarvisOrchestratorAgent (OrchestratorAgent) --+
                       |   persona + regras identity + memória relevante + snapshot
                       |   _check_tool_allowed -> política de autonomia -> ALLOW/ASK/DENY
                       |   ASK -> callback interativo | pendência para aprovação
                       v
        ToolExecutor (RBAC, taint, injection scan) -> lifeos_memory | lifeos_planner | lifeos_review | ferramentas nativas
                       |
                     LifeOS (fachada)
     +-----------+-----------+-----------+-------------+--------------+
     | Memory    | Planner   | Reviews   | Autonomy    | ActionLog    |
     | 5 camadas | metas...  | alertas   | níveis 1-4  | hash chain   |
     +-----------+-----------+-----------+-------------+--------------+
                       |
                 SQLite local (WAL, FTS5)  ~/.openjarvis/lifeos/lifeos.db
```

Fluxo de um pedido (os 10 passos do orquestrador):

1. entender o pedido (modelo);
2. contexto: persona, regras `identity`, memórias relevantes (FTS5 + semântica
   opcional), snapshot operacional com alertas;
3. consultar memória sob demanda (`lifeos_memory search`);
4. classificar (guia de roteamento no prompt);
5. selecionar especialista — Fase 2;
6. planejar (persona/guia);
7. verificar risco: cada chamada de ferramenta passa pela política;
8. executar ou solicitar autorização;
9. conferir: resultados das ferramentas voltam ao modelo;
10. registrar: auditoria automática, conversa persistida, memória quando útil.

## 4. Estrutura de diretórios

```
src/openjarvis/lifeos/
  __init__.py      exporta LifeOS
  config.py        lifeos.toml (separado)
  db.py            esquema SQLite versionado, FTS5
  memory.py        memória em camadas
  planner.py       metas, projetos, tarefas, hábitos, compromissos, decisões
  reviews.py       alertas e revisões
  autonomy.py      política de autonomia por risco
  audit.py         registro de ações com cadeia de hashes
  persona.py       persona padrão (persona.md editável)
  service.py       fachada LifeOS
  tools.py         ferramentas para agentes
  agent.py         jarvis_orchestrator
  cli.py           jarvis lifeos ...
  api.py           /v1/lifeos e /lifeos
  static/dashboard.html
tests/lifeos/      53 testes
docs/user-guide/lifeos.md
docs/architecture/lifeos.md
```

Alterações em arquivos originais (aditivas, 32 linhas, com `try/except` para
não derrubar o OpenJarvis se o LifeOS falhar):
`agents/__init__.py`, `tools/__init__.py`, `cli/__init__.py`, `server/app.py`.

## 5. Plano por etapas

**Fase 1 — Fundação (concluída).** Agente central, persona, memória em
camadas, LifeOS, revisões e alertas, autonomia, aprovações, auditoria, CLI,
API, painel, documentação, testes.

**Fase 2 — Inteligência.** Especialistas (PERSONAL_MANAGER,
STRATEGIC_ADVISOR, STUDY_MENTOR, FINANCIAL_ADVISOR, CAREER_BUILDER,
HEALTH_AND_FITNESS, EMOTIONAL_ADVISOR, RESEARCH_ANALYST,
EXECUTIVE_ASSISTANT, MEMORY_MANAGER) como perfis (prompt + conjunto de
ferramentas + camadas de memória visíveis) executados por uma ferramenta
`delegate` do orquestrador; contexto compartilhado controlado por camada;
registro episódico automático de decisões; avaliação com o motor real.

**Fase 3 — Organização.** Revisões guiadas (perguntas), indicadores por meta,
histórico de decisões com acompanhamento de resultado.

**Fase 4 — Automações.** Agendar revisões no `scheduler` nativo; entrega via
canal (Telegram) respeitando limite de notificações; conectores Google
oficiais (OAuth já existente no OpenJarvis); regras de arquivos do Windows
com gatilho/condição/ação/permissão/registro.

**Fase 5 — Evolução.** Métricas por agente a partir da auditoria, testes de
regressão com o modelo escolhido, otimização de prompts.

## 6. Riscos técnicos e dependências

- **Qualidade do modelo local**: chamadas de ferramenta dependem de um modelo
  com function calling confiável. Modelos pequenos erram argumentos; os erros
  voltam ao modelo como resultado da ferramenta, sem efeito colateral.
- **Hardware desconhecido**: define modelo e se a busca semântica é viável.
- **FTS5**: presente no Python oficial do Windows; sem ele, a busca cai para
  `LIKE` automaticamente.
- **Concorrência**: uma conexão SQLite por processo com lock; CLI e servidor
  simultâneos usam WAL e `busy_timeout`.
- **Fuso horário**: datas de tarefas são locais; carimbos de auditoria em UTC.
- **Base instável**: 79 testes já falham no OpenJarvis upstream.

## 7. Decisões que dependem do usuário

1. Hardware (CPU, RAM, GPU/VRAM) e modelo de linguagem a usar.
2. Ativar busca semântica e qual modelo de embeddings.
3. Nível de autonomia inicial (padrão: 2) e categorias pré-autorizadas.
4. Canal de notificações (Telegram ou outro) e horários das revisões.
5. Integrações Google: quais contas e escopos.
6. Pastas do Windows que o JARVIS pode organizar e regras.
7. Repositório/fork onde publicar o código.
