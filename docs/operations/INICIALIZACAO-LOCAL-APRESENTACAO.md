# Inicialização Local e Contingência — Apresentação DatumLex

Guia operacional curto para iniciar, verificar e diagnosticar o ambiente local real do DatumLex (`datumlex_ops_f3_full`, coorte `civil-2010-sgt-2026-11`, 4.518 registros DataJud e 2 precedentes oficiais do STJ), especialmente após reiniciar o Mac.

## Endereço e serviços locais

- **Aplicação (React/Vite):** `http://127.0.0.1:5173/`
- **Backend (Django/Gunicorn):** `http://127.0.0.1:58003` (proxy em `/api/health/`)
- **Banco (PostgreSQL 17 isolado):** `127.0.0.1:55437` · banco `datumlex_ops_f3_full`
- **Garantias de segurança:** somente loopback (`127.0.0.1`), `DATUMLEX_SYNTHETIC_PREVIEW=false`, `RESEARCH_GEMINI_ENABLED=false`, `GEMINI_API_KEY=""`, `DATUMLEX_PUBLIC_REGISTRATION_COURTS=STJ,TJDFT,TJMG,TJPR,TJRJ,TJRS,TJSP,TRF1,TRF3`, sem migrações, ETL ou alteração de arquivos privados.

---

## 1. Iniciar o DatumLex após reiniciar o Mac

A partir da raiz do repositório oficial (`/Users/pedromattos/Documents/DatumLex/datumlex-core`):

```sh
./scripts/datumlex-local.sh start
```

O script:
1. Valida a configuração local (`../recuperacao/local-env`), o cluster isolado `../recuperacao/pg` e o runtime Python/Node.
2. Verifica se já existem processos nas portas `55437`, `58003` e `5173` (não duplica nem encerra processos existentes).
3. Inicia apenas os serviços ausentes na ordem: **PostgreSQL 17** → **validação SQL somente leitura do banco e coorte** → **Django/Gunicorn** → **React/Vite**.
4. Valida `/api/health/` diretamente e pelo proxy Vite, exibindo ao final `http://127.0.0.1:5173/`.

Para apenas simular sem iniciar nada:

```sh
./scripts/datumlex-local.sh --dry-run
```

---

## 2. Verificar que está funcionando

Execute o diagnóstico somente leitura (nunca inicia nem encerra processos e não revela segredos):

```sh
./scripts/datumlex-local.sh --check
```

Confirme no relatório:
- **PostgreSQL:** `OK` na porta `55437`
- **Verificação SQL somente leitura:** `OK` (`banco=datumlex_ops_f3_full`, `coorte=True`, `membros=4518`, `tribunais=9`)
- **Django:** `OK` em `127.0.0.1:58003` (modo real, não sintético)
- **Vite e Proxy `/api/health/`:** `OK` em `127.0.0.1:5173`
- **Gemini:** desativado (`false`)

---

## 3. Fazer login

1. Abra `http://127.0.0.1:5173/` no Safari ou Chrome.
2. Entre com a conta local de demonstração (ou utilize **Criar conta** para demonstrar o cadastro imediato com perfil `Padrão` e os 9 tribunais locais).
3. Recarregue a página (`Cmd+R`) para confirmar a persistência de sessão.
4. Confira na tela **Pesquisa processual**: **4.518 documentos DataJud** / **4.516 números CNJ distintos**.

---

## 4. Erros mais prováveis e como resolver

| Sintoma | Causa provável | Ação segura |
|---|---|---|
| `Porta 55437 / 58003 / 5173 ocupada por processo inesperado` | Outro serviço (ou outra worktree) está usando a porta. | Verifique o PID mostrado pelo `--check` (`lsof -nP -iTCP:<porta> -sTCP:LISTEN`), encerre manualmente apenas o processo conflitante e rode `./scripts/datumlex-local.sh start`. |
| `PostgreSQL não está respondendo` | Cluster isolado parado após reinício do Mac ou `pg_ctl` fora do PATH. | Confirme `which pg_ctl` (Homebrew em `/opt/homebrew/bin`), verifique `../recuperacao/pg.log` e execute `./scripts/datumlex-local.sh start`. |
| `Banco conectado diverge` ou `Coorte ausente` | Configuração privada inconsistente ou banco errado na porta `55437`. | O script bloqueia a subida do Django por segurança. Não rode migrações; verifique qual banco está ativo na porta `55437` e confira os dumps íntegros em `../recuperacao/`. |
| `Django/Gunicorn não ficou saudável` | Erro ao subir Gunicorn ou conflito de dependência Python. | Inspecione `../recuperacao/local-django.log` (últimas 40 linhas) sem expor credenciais. |
| `Vite não respondeu` ou `node_modules não encontrado` | Dependências frontend ausentes no clone. | No diretório `frontend`, confirme `node_modules` e consulte `../recuperacao/local-vite.log`. |
| Cadastro retorna `503` (`nenhum tribunal padrão`) | Gunicorn foi iniciado antes, fora do script, sem `DATUMLEX_PUBLIC_REGISTRATION_COURTS`. | Reinicie o Gunicorn de forma controlada via `./scripts/datumlex-local.sh start` (após parar o processo antigo). |

---

## 5. Diagnóstico seguro durante a apresentação

Se algo falhar ao vivo durante a apresentação:
1. Primeiro clique em **Tentar novamente** na própria interface (recupera erros temporários 503).
2. Se persistir, abra um terminal fora da tela compartilhada e rode **somente leitura**:
   ```sh
   ./scripts/datumlex-local.sh --check
   ```
   (A saída nunca imprime senhas, chaves ou `DATABASE_URL`.)
3. Se algum serviço específico tiver caído, suba apenas o serviço ausente sem derrubar os demais:
   ```sh
   ./scripts/datumlex-local.sh start
   ```
