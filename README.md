# Combinado — servidor

Servidor que liga o WhatsApp (API oficial da Meta) ao Google Agenda de cada
barbearia, usando uma IA (hoje OpenAI, trocável para Claude depois) para
conversar com o cliente e marcar/remarcar/cancelar horários sozinho, além de
um "modo dono" para o fechamento do dia.

## Estrutura

```
src/
  config.js        - cadastro dos clientes (barbearias) e variáveis de ambiente
  scheduling.js     - contas de horário (dia útil, almoço, o que cabe onde)
  googleCalendar.js - fala com o Google Agenda (ler, criar, mover, cancelar eventos)
  tools.js          - "ferramentas" que a IA usa no atendimento normal do cliente
  ownerTools.js     - ferramentas do modo dono (fechamento do dia)
  ownerSession.js   - controle de código de acesso do modo dono
  prompts.js        - instruções (system prompt) da IA, cliente e dono
  ai.js             - chamada à OpenAI com "tools" (function calling)
  whatsapp.js       - enviar/receber mensagens pela Graph API da Meta
  state.js          - histórico de conversa em memória
  store.js          - guarda o fechamento do dia em arquivos JSON
  reminders.js       - lembrete automático da véspera (cron diário)
  index.js          - servidor Express (webhook do WhatsApp)
tests/
  logic-test.js     - testa as contas de agenda e as ferramentas sem precisar
                      de credenciais de verdade (substitui o Google Agenda por
                      uma agenda falsa em memória)
```

## 1. Preparar

```bash
npm install
cp .env.example .env
```

Preencha o `.env`:

- `WHATSAPP_TOKEN`: token da Meta (Meta for Developers > WhatsApp > Configuração da API). Comece com o temporário para testar.
- `OPENAI_API_KEY`: chave criada em platform.openai.com > API keys.
- `GOOGLE_SERVICE_ACCOUNT_KEY_PATH`: caminho do JSON da conta de serviço baixado no Google Cloud Console. Coloque o arquivo em `secrets/combinado-servidor.json` (a pasta `secrets/` já está no `.gitignore`, não vai pro Git).
- `ELIAS_PHONE_NUMBER_ID`: em Meta for Developers > WhatsApp > Configuração da API ("Phone Number ID").
- `ELIAS_CALENDAR_ID`: Google Agenda "Barbearia do Elias" > Configurações e compartilhamento > Integrar agenda > ID da agenda.
- `ELIAS_OWNER_PHONE`: WhatsApp do Elias, só números (ex: `5521999999999`).
- `ELIAS_OWNER_CODE`: o código de 4 dígitos que ele vai usar no modo dono.
- `ELIAS_REMINDER_TEMPLATE`: nome do template aprovado pela Meta para o lembrete da véspera (veja a seção abaixo).

Não esqueça: a agenda do Google precisa estar **compartilhada** com o
e-mail da conta de serviço (o que termina em `.iam.gserviceaccount.com`),
com permissão "Fazer alterações nos eventos".

## 2. Testar a lógica sem credenciais

```bash
npm run test:logic
```

Isso roda um teste que substitui o Google Agenda por uma agenda falsa em
memória e confere se marcar, remarcar, trocar de serviço, cancelar e o
fechamento do dia calculam certo. Não manda nenhuma mensagem de verdade nem
precisa de chave da OpenAI ou do Google.

## 3. Rodar local

```bash
npm start
```

O servidor sobe na porta definida em `PORT` (padrão 3000) com um endpoint
`/webhook` (GET para verificação da Meta, POST para receber mensagens).

Para a Meta conseguir chamar seu `/webhook` rodando localmente, use algo como
o `ngrok` (`ngrok http 3000`) durante os testes.

## 4. Configurar o Webhook na Meta

Em Meta for Developers > WhatsApp > Configuração > Webhooks:

- Callback URL: `https://SEU-DOMINIO/webhook`
- Verify Token: o mesmo valor de `WHATSAPP_VERIFY_TOKEN` no `.env`
- Assine o campo `messages`

## 5. Criar o template do lembrete da véspera

Mensagens que a barbearia inicia (o cliente não escreveu nada nas últimas
24h) só podem ser enviadas como "template" aprovado pela Meta. Crie um em
Meta for Developers > WhatsApp > Modelos de mensagem:

- Nome: o mesmo valor de `ELIAS_REMINDER_TEMPLATE` (ex: `lembrete_vespera`)
- Categoria: Utilidade
- Corpo: `Oi {{1}}! Passando pra lembrar do seu horário amanhã às {{2}}, {{3}}. Responda 1 para confirmar ou 2 para remarcar.`

A aprovação da Meta geralmente sai em minutos a poucas horas.

## 6. Colocar no ar (deploy)

Qualquer serviço que rode Node.js continuamente serve (Render, Railway,
Fly.io etc.). Passos gerais, usando o **Render** como exemplo:

1. Suba este projeto num repositório Git (GitHub, por exemplo) — sem a pasta
   `secrets/` nem o `.env` (já ficam de fora pelo `.gitignore`).
2. No Render, crie um **Web Service** apontando para o repositório.
3. Build command: `npm install`. Start command: `npm start`.
4. Em "Environment", cadastre as mesmas variáveis do `.env` (uma por uma).
5. O JSON da conta de serviço do Google: cole o conteúdo inteiro numa
   variável de ambiente (ex: `GOOGLE_SERVICE_ACCOUNT_JSON`) em vez de um
   arquivo, e ajuste `src/googleCalendar.js` para escrever esse conteúdo num
   arquivo temporário na inicialização — ou use o recurso de "Secret Files"
   do próprio Render, que resolve isso sem mexer no código.
6. Depois do primeiro deploy, atualize a Callback URL do Webhook na Meta
   para a URL pública que o Render deu (ex:
   `https://combinado-servidor.onrender.com/webhook`).

## Limitações conhecidas (para evoluir depois)

- O histórico de conversa e o estado do modo dono ficam **em memória**: se o
  servidor reiniciar, uma conversa em andamento recomeça do zero. Para um
  volume maior de clientes, vale trocar por um banco de dados (Postgres,
  Redis etc.).
- O fechamento do dia é salvo em arquivos JSON simples em `data/closings/`.
  Funciona bem para poucos clientes; se crescer, migrar para um banco.
- Hoje a IA é a OpenAI (`gpt-4o-mini`, mais barato). Para trocar para o
  Claude (Anthropic) quando houver orçamento, o único arquivo que precisa
  mudar é `src/ai.js` — o resto (regras, ferramentas, agenda) continua igual.
- Um novo cliente (outra barbearia) se cadastra copiando o bloco do Elias em
  `src/config.js`, com suas próprias variáveis de ambiente.
