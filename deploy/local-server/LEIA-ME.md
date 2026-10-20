# Instalar o DatumLex em um servidor local Windows

## Na maquina que sera o servidor

1. Use Windows 10/11 compativel com Docker Desktop, virtualizacao habilitada e internet para baixar as dependencias. Este pacote nao e destinado a Windows Server. Reserve o IPv4 da maquina no roteador (exemplo: 192.168.1.100) e configure a rede do Windows como Privada.
2. Extraia TODO o ZIP para uma pasta. Nao execute dentro do ZIP. Abra **INSTALAR.cmd** com dois cliques, usando a conta Windows que operara o servidor.
3. Se Docker Desktop nao estiver instalado, o instalador usa o winget para instala-lo. Conclua as telas do Docker/WSL e aceite os termos aplicaveis. Se for solicitado, reinicie o Windows e execute INSTALAR.cmd novamente. Se winget nao estiver disponivel, instale Docker Desktop pelo site oficial e repita.
4. Digite o IPv4 local mostrado pelo instalador. Autorize a configuracao do firewall quando o Windows solicitar. Somente a porta HTTPS 443 fica acessivel pela sub-rede local nos perfis Privado/Dominio; o PostgreSQL e o backend nao publicam portas.
5. Aguarde a compilacao e a verificacao de saude. Na primeira instalacao, os downloads podem levar varios minutos. O navegador abre o DatumLex.
6. Acesse `%LOCALAPPDATA%\DatumLexServer\ACESSO-INICIAL.txt` para consultar o usuario **suport** e a senha aleatoria. Guarde-os em local privado. Pelo menu Usuarios, crie/aprove as contas e atribua os tribunais.

O aplicativo e instalado em `%LOCALAPPDATA%\DatumLexServer`. O banco fica no volume Docker `datumlex-server_database`. Reexecutar o instalador preserva a configuracao e esse volume. Nunca use `docker compose down -v`, remova o volume ou restaure o Docker aos padroes de fabrica sem backup.

## Nos computadores clientes

Copie **somente** a pasta `%LOCALAPPDATA%\DatumLexServer\clientes` do servidor para cada cliente Windows. Execute **Configurar-Cliente.cmd** uma vez por usuario Windows. Ele instala o certificado publico da autoridade HTTPS local e abre o endereco do sistema. O Windows pode pedir confirmacao de confianca no certificado. Use a copia fornecida pelo responsavel pelo servidor.

Depois, basta abrir **DatumLex.url** ou acessar `https://IP-DO-SERVIDOR` pelo navegador. Nao e preciso instalar Docker, Python ou Node nos clientes. Edge e Chrome usam o repositorio de certificados do Windows; outros navegadores/dispositivos podem exigir a importacao manual de `DatumLex-Raiz.crt`.

Nao compartilhe a pasta completa do servidor, o arquivo `.env`, ACESSO-INICIAL.txt nem os volumes de certificados. A pasta clientes contem somente o certificado PUBLICO e os atalhos, nunca a chave privada da autoridade.

## Uso diario e backups

- **DatumLex - Iniciar**: inicia Docker Desktop se necessario e os containers, verifica o servidor e abre o navegador.
- **DatumLex - Parar**: para os containers sem apagar dados. O acesso de todos os clientes sera interrompido.
- **DatumLex - Backup**: gera um backup PostgreSQL em `%LOCALAPPDATA%\DatumLexServer\backups`. O banco precisa estar em execucao. Copie os backups para outra unidade/maquina e proteja seu acesso. O pacote inclui backup manual; nao agenda backups automaticamente.
- No Docker Desktop, ative a opcao de iniciar ao entrar no Windows. Os containers configurados com `unless-stopped` retomam quando o Docker inicia, exceto se voce os parou explicitamente. Nesse caso use Iniciar. Docker Desktop depende da sessao do usuario; este pacote nao implementa um servico Windows que funcione antes do login.
- Mantenha o servidor ligado, conectado a rede e sem suspensao durante o atendimento.

O banco inicial vem vazio, com a estrutura, o tribunal inicial e a conta de suporte. O instalador NAO transfere dados desta maquina de desenvolvimento. A importacao dos registros judiciais deve ser planejada separadamente. O arquivo `deploy\local-server\.env` da instalacao permite configurar DATAJUD_API_KEY quando necessario; a extracao nao e executada pelo instalador.

## Recuperacao e atualizacoes

Este pacote prepara uma instalacao nova, separada do banco usado no desenvolvimento. Nao aponte o instalador para bancos antigos v1: ha uma migracao historica que recria tabelas. Antes de instalar uma nova versao, faca backup. Migracoes de versao precisam ser revisadas por quem distribui a atualizacao.

Para restauracao assistida, pare backend/web, copie um arquivo `.dump` para o container db e use `pg_restore` com o usuario datumlex em um banco limpo. Restaurar sobre dados atuais substitui informacoes: valide primeiro em ambiente separado. O backup `.dump` nao inclui a configuracao `.env` nem os volumes de certificados; preserve esses itens separadamente em armazenamento privado. Sem a autoridade original, sera necessario confiar no novo certificado em todos os clientes.

Se o IP mudar, reserve o novo endereco, ajuste SERVER_HOST e execute Instalar novamente; redistribua o atalho atualizado. Se a porta 443 estiver ocupada, resolva o conflito antes de instalar. Se a instalacao falhar, o terminal mostra a etapa e permite repetir sem apagar os dados.

## Para quem gera o pacote

Execute `python deploy/local-server/build-package.py CAMINHO-DO-ZIP` na raiz do projeto. O empacotador inclui codigo e configuracao de distribuicao, excluindo ambientes virtuais, bancos, `.env`, dependencias locais e credenciais. A primeira instalacao baixa imagens e dependencias; nao e um pacote offline nem um executavel assinado.

Referencias: [Docker Desktop no Windows](https://docs.docker.com/desktop/setup/install/windows-install/) e [HTTPS local do Caddy](https://caddyserver.com/docs/automatic-https).
