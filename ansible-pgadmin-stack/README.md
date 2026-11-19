# PostgreSQL and pgAdmin on Ubuntu 24.04

This Ansible project targets `ngninxpg` at `192.168.122.86` over SSH as `volodymyr`. The inventory group is `database`. After deployment, open <http://192.168.122.86/> on your lab network.

```text
Browser ── HTTP :80 or HTTPS :443 ──> Nginx
Nginx ── Unix domain socket ──> Gunicorn ── WSGI ──> pgAdmin 4
pgAdmin 4 ── TCP 127.0.0.1:5432 ──> PostgreSQL
```

Nginx accepts browser requests and proxies them to Gunicorn. Gunicorn runs the pgAdmin Python application under systemd. pgAdmin is the browser-based database administration interface. PostgreSQL stores the lab data, and pgAdmin keeps its own accounts and preferences in a separate SQLite database. The stack runs directly on Ubuntu without containers or an Apache dependency.

## Files and roles

| File or directory | Purpose |
| --- | --- |
| `ansible.cfg` | Selects the project inventory and role directory, enables SSH pipelining, and keeps host key checking enabled. |
| `inventory.ini` | Defines the managed VM and its SSH user. |
| `site.yml` | Runs the preflight and applies the roles in dependency order. |
| `requirements.yml` | Pins the PostgreSQL collection used by the verification playbook. |
| `group_vars/all.yml` | Sets lab database names and Nginx hostnames for this inventory. |
| `group_vars/all/vault.yml.example` | Lists the secret keys. Create the adjacent encrypted `vault.yml` locally. |
| `.gitignore` | Keeps the local Vault file, password files, retry files, and Python caches out of Git. |
| `roles/common/` | Installs Ubuntu runtime prerequisites, including Python venv, psycopg2, ACL tools, curl, and CA certificates. |
| `roles/postgresql/` | Checks existing clusters, installs PostgreSQL when needed, and starts it. `files/provision_lab.py` creates the lab login and database if absent and grants the lab login `CREATEDB`. |
| `roles/pgadmin/` | Inspects existing web installations, installs pinned Python wheels, renders `config_local.py`, and initializes a new SQLite database with `files/bootstrap.py`. |
| `roles/gunicorn/` | Owns `gunicorn.service.j2`, the restart handler, and the socket health check. |
| `roles/nginx/` | Owns the virtual host, candidate validation, reload, HTTP probes, and site rollback. |
| `tests/verify.yml` | Runs standalone service, listener, database, and HTTP checks on the VM. |

Each role's `defaults/main.yml` contains overridable settings. Its `tasks/main.yml` is the normal entry point. The Gunicorn and Nginx handlers run when relevant configuration changes. The common, PostgreSQL, and pgAdmin roles have empty handler files because their tasks delegate web-service lifecycle changes to the Gunicorn role.

The official pgAdmin wheel runs inside a root-owned venv under `/opt/ansible-pgadmin`. The role resolves the pinned wheels on the target and checks the installed WSGI module. Pip requires wheels for pgAdmin and Gunicorn, prefers wheels for dependencies, and can build source-only dependencies such as `jsonformatter` and `Flask-Principal`. Gunicorn uses one worker with multiple threads to preserve pgAdmin database-session affinity. systemd creates the runtime directory and Gunicorn binds its socket. Nginx accesses the socket through the worker group. [pgAdmin server deployment guide](https://www.pgadmin.org/docs/pgadmin4/development/server_deployment.html)

## Configure the project

Run commands from `ansible-pgadmin-stack/`. Install the verification collection and enroll the VM SSH key after checking its fingerprint.

```bash
ansible-galaxy collection install -r requirements.yml
ssh volodymyr@192.168.122.86
```

Create the local encrypted file with your editor. Choose a strong Vault password and keep it in your password manager.

```bash
umask 077
ansible-vault create group_vars/all/vault.yml
```

Enter a YAML mapping with these three keys and your own values. Quote YAML values as needed. Store each password as a distinct secret of at least 12 characters.

| Vault key | Used for |
| --- | --- |
| `vault_postgresql_lab_password` | Provisioning the PostgreSQL lab login when absent. Existing passwords are preserved. |
| `vault_pgadmin_admin_email` | Initial pgAdmin web login email on a fresh installation. |
| `vault_pgadmin_admin_password` | Initial pgAdmin web login password on a fresh installation. |

Edit the encrypted file later with:

```bash
ansible-vault edit group_vars/all/vault.yml
```

The actual `vault.yml` is created by this command on your control node. The shipped example contains variable names only. Passwords pass through task stdin under `no_log` and the PostgreSQL helper sends a SCRAM verifier to the database server. Existing pgAdmin accounts and PostgreSQL passwords are managed through their respective administration interfaces after deployment.

| Variable | Default or purpose |
| --- | --- |
| `postgresql_lab_user`, `postgresql_lab_database` | `pgadmin_lab` for each. Choose unused names when sharing an existing cluster. |
| `pgadmin_server_names` | Inventory hostname and VM address. Use certificate names for TLS. |
| `pgadmin_listen_port` | `80` for the local lab. |
| `pgadmin_version`, `pgadmin_gunicorn_version` | Pinned pgAdmin and Gunicorn releases. An existing pgAdmin SQLite database requires a separate maintenance plan for a pgAdmin version change. |
| `pgadmin_gunicorn_threads` | `8` threads in the single worker. |
| `pgadmin_nginx_worker_user`, `pgadmin_nginx_worker_group` | `www-data` for Ubuntu Nginx. Align these with a customized Nginx service. |
| `pgadmin_socket_path` | `/run/pgadmin-gunicorn/pgadmin.sock`. |
| `pgadmin_min_free_kib` | Minimum free disk capacity per checked filesystem, 2 GiB by default. |

### Optional HTTPS

Override these settings in `group_vars/all.yml`. Install the certificate chain and key on the VM first. Set `pgadmin_server_names` to names covered by the certificate, and trust the issuing CA on the VM and in your browser.

```yaml
pgadmin_server_names:
  - pgadmin.example.org
pgadmin_use_https: true
pgadmin_https_port: 443
pgadmin_tls_certificate: /etc/ssl/certs/pgadmin-fullchain.pem
pgadmin_tls_private_key: /etc/ssl/private/pgadmin.key
```

Nginx redirects HTTP to HTTPS and pgAdmin adds the Secure cookie attribute. `pgadmin_probe_validate_certs` defaults to true. Use valid DNS or an appropriate hosts entry for browser access. The playbook probes the VM's local Nginx listener with the configured TLS name. For this lab's HTTP mode, traffic and credentials travel in cleartext on the VM network. Keep HTTP confined to a trusted lab network.

## Preflight and deployment

Choose the SSH authentication prompts appropriate for your environment. Omit `--ask-pass` if SSH keys are configured. The password prompt requires the controller's password-SSH support.

```bash
ansible-playbook -i inventory.ini site.yml --syntax-check --ask-vault-pass
ansible-playbook -i inventory.ini tests/verify.yml --syntax-check --ask-vault-pass

ansible-playbook -i inventory.ini site.yml --tags preflight \
  -e '{"pgadmin_preflight_only":true}' \
  --ask-pass --ask-become-pass --ask-vault-pass

ansible-playbook -i inventory.ini site.yml --check --diff \
  --ask-pass --ask-become-pass --ask-vault-pass
```

The preflight inspects Ubuntu and Python versions, disk capacity, package state and cached origins, PostgreSQL clusters, Nginx includes, Apache dependencies and enabled sites, relevant systemd units and listeners, and common pgAdmin installation and data paths. It stops on ambiguous pgAdmin installations, conflicting listeners, and PostgreSQL layouts that need operator review. The PostgreSQL role supports a clean Ubuntu installation or a single automatically started Ubuntu cluster on port 5432 with loopback-only listening and local peer authentication for maintenance. It preserves cluster authentication and configuration. Apache can stay installed if it does not own a requested port.

Check mode runs inspection and variable validation. Apt installation, PyPI resolution, candidate activation, SQLite initialization, and running-service checks occur during a real run. Inspect findings before approving deployment. Installation needs access to the configured Ubuntu archives and PyPI. Run one deployment per VM at a time because the Nginx rollback protects the managed site and assumes no concurrent edits to the surrounding Nginx configuration.

```bash
ansible-playbook -i inventory.ini site.yml \
  --ask-pass --ask-become-pass --ask-vault-pass

ansible-playbook -i inventory.ini tests/verify.yml \
  --ask-pass --ask-become-pass --ask-vault-pass
```

Run the same deployment command a second time with the same settings and look for `changed=0` and `failed=0`. A first run creates the required resources. Later runs use the SQLite database and lab objects already present and reload services only when their configuration changes.

Open <http://192.168.122.86/> and sign in with the pgAdmin Vault email and password. To connect to the lab database, choose **Register → Server** inside pgAdmin. Use `127.0.0.1`, port `5432`, the lab database as the maintenance database, and the PostgreSQL lab login and password. pgAdmin itself makes this connection on the VM. The lab login can now create additional databases through **Databases → Create → Database**.

## Verify and troubleshoot on the VM

```bash
systemctl is-active postgresql pgadmin-gunicorn nginx
systemctl is-enabled postgresql pgadmin-gunicorn nginx
pg_lsclusters
pg_isready -h 127.0.0.1 -p 5432
sudo ss -ltnp
sudo ss -lxnp | grep pgadmin
sudo nginx -t
sudo -u www-data curl --unix-socket /run/pgadmin-gunicorn/pgadmin.sock -I http://localhost/login
curl -I http://192.168.122.86/login
sudo journalctl -u pgadmin-gunicorn -u nginx -u postgresql -n 100 --no-pager
sudo tail -n 50 /var/log/ansible-pgadmin/pgadmin4.log /var/log/nginx/error.log
```

The pgAdmin 9.19 wheel omits generated JavaScript and CSS. The role fills in the matching static files from the checksum-pinned upstream Ubuntu archive and checks the login bundle and stylesheet through Nginx.

For a 502, check the Gunicorn journal, socket ownership and permissions, and Nginx worker identity. For wrong-site routing, review `sudo nginx -T` privately and look for conflicting `server_name` and `listen` directives. A fresh-install credential error is intentionally hidden from the Ansible log. Check the names and YAML quoting with `ansible-vault edit`. Gunicorn access and error logs go to the systemd journal. pgAdmin state and logs use private service-owned directories.

## PostgreSQL binary paths in pgAdmin

The message **Utility file not found. Please correct the Binary Path in the Preferences** means pgAdmin could not locate the executable required by an operation. Backup uses `pg_dump`, global backups use `pg_dumpall`, and archive restore uses `pg_restore`. Plain SQL restore and the PSQL Tool use `psql`. The browser's Query Tool uses pgAdmin's PostgreSQL driver. The screen or operation that triggered the error can identify the specific missing executable.

The PostgreSQL role reads the cluster version from `pg_lsclusters`, derives `/usr/lib/postgresql/<major>/bin`, and ensures `postgresql-client-<major>` is installed. The pgAdmin role checks all four client programs with `--version` as `pgadmin-web`. It then sets a version-specific default and fixed path in `config_local.py`. The fixed path takes precedence over an existing user preference for that PostgreSQL version. The Gunicorn handler applies the configuration when the file changes. [pgAdmin configuration reference](https://www.pgadmin.org/docs/pgadmin4/9.19/config_py.html)

To investigate on the VM, run:

```bash
pg_lsclusters
command -v psql pg_dump pg_restore pg_dumpall
pg_config --bindir
```

On Ubuntu, the commands found in `/usr/bin` can be wrappers. If `pg_config` is missing or reports another version, use the major shown by `pg_lsclusters` on port 5432. Check the exact package and file paths with:

```bash
major=$(pg_lsclusters --no-header | awk '$3 == 5432 { print $1 }')
dpkg-query -W "postgresql-client-$major"
for utility in psql pg_dump pg_restore pg_dumpall; do
  sudo -u pgadmin-web "/usr/lib/postgresql/$major/bin/$utility" --version
done
```

In pgAdmin, open **File → Preferences → Paths → Binary paths**. In the **PostgreSQL Binary Path** grid, locate the row for the server major and use **Validate Path** to check the utilities. The Ansible-managed row is read-only. For a server version whose path is user-editable, enter the matching binary directory in that row, validate it, and save. [pgAdmin preferences](https://www.pgadmin.org/docs/pgadmin4/9.19/preferences.html#the-paths-node)

If a package is listed as installed but the file is missing, run `dpkg -V "postgresql-client-$major"` to check package files. If the binaries work from the VM but pgAdmin still reports an error, check the server major in pgAdmin, the configured row, and `sudo journalctl -u pgadmin-gunicorn -n 50 --no-pager`. Run `tests/verify.yml` to check the live PostgreSQL version, the client tools, Gunicorn, and Nginx without running a restore.

## Rollback

The Nginx role stages the candidate alongside a copy of the enabled site entries in a private mount namespace. It checks the complete effective configuration with `nginx -t` and confirms the candidate is included. After installing the site, it reloads Nginx and verifies the pgAdmin login through each hostname. If activation or verification fails, it restores the previous managed site or removes the newly created one. If Nginx started during the failed attempt, it returns it to its previous stopped state. The role requires mount namespaces and mount permissions for root on the VM.

For a manual web rollback, restore the intended backup from `/var/backups/ansible-pgadmin/` to `/etc/nginx/sites-enabled/zz-ansible-pgadmin.conf`. For a new site with no prior version, move the managed site out of `sites-enabled`. Validate with `sudo nginx -t`, then run `sudo systemctl reload nginx`.

Ansible keeps prior copies of the Gunicorn unit and pgAdmin's `config_local.py` when it replaces them. If a Gunicorn change fails, restore the matching copies, run `sudo systemctl daemon-reload` and `sudo systemctl restart pgadmin-gunicorn`, then run the socket probe. When reverting a TLS change, restore the pgAdmin cookie and Nginx proxy settings together. To take the application offline, disable the managed Nginx site and stop and disable `pgadmin-gunicorn`.

Keep backups of `/var/lib/ansible-pgadmin` and PostgreSQL data using the appropriate application backup methods. Proxy rollback preserves both stores and the lab login. Application upgrades, migration of an existing installation, database deletion, and password rotation are separate maintenance operations.
