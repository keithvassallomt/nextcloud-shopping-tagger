# Nextcloud Shopping Tagger

Watches a shopping list in the Nextcloud **Tasks** app and uses OpenAI to give each new item one of your predefined tags (e.g. *Fruit & Veg*, *Dairy*, *Household*). Tags show up in the Tasks app, so you can sort or filter the list by supermarket aisle.

- Only open (not completed) items without one of your tags are sent to the AI.
- The AI can only answer with one of your tags (OpenAI structured outputs with an enum).
- Other tags the family adds by hand (e.g. "Urgent") are kept.
- Items are sent in batches, so a pass costs a fraction of a cent with `gpt-5-mini`.

## Setup

1. **App password:** in Nextcloud go to *Settings → Security → Devices & sessions → Create new app password*.
2. **Config:** copy `.env.example` to `.env` and fill it in. `TAGS` must match the tags you want, spelled exactly.
3. **Dry run first:** leave `DRY_RUN=true`, start the container, and check the logs:
   ```
   2026-10-26 19:30:01 INFO 2kg apples                     -> Fruit & Veg
   ```
   When the tags look right, set `DRY_RUN=false` and redeploy.

## Run with Docker Compose

```sh
docker compose up -d --build
docker compose logs -f
```

## Run in Portainer

Deploy straight from this Git repository, and Portainer builds the image for you:

1. *Stacks → Add stack*, name it `shopping-tagger`, choose **Repository**.
2. Repository URL: `https://github.com/keithvassallomt/nextcloud-shopping-tagger`, reference `refs/heads/main`, compose path `docker-compose.yml`.
3. Optional: turn on **GitOps updates** (polling) so pushes to `main` redeploy automatically.
4. Under *Environment variables*, use **Load variables from .env file** with your filled-in `.env`, then check the list.
5. **Deploy the stack**, then watch *Containers → shopping-tagger → Logs*.

To update manually, open the stack and click **Pull and redeploy**. The compose file uses `pull_policy: build`, so every deploy rebuilds the image from the latest code. Your secrets live only in Portainer's stack variables, never in the repo.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `NEXTCLOUD_URL` | required | Server root, e.g. `https://cloud.example.com` |
| `NEXTCLOUD_USER` | required | |
| `NEXTCLOUD_APP_PASSWORD` | required | App password, not your login password |
| `LIST_NAME` | `Shopping` | Display name of the Tasks list (case-insensitive) |
| `TAGS` | required | Comma-separated list of allowed tags |
| `TAGS_SEPARATOR` | `,` | Set to e.g. `\|` if a tag contains a comma: `TAGS=Meat, Fish & Poultry\|Dairy` |
| `OPENAI_API_KEY` | required | |
| `OPENAI_MODEL` | `gpt-5-mini` | Any model that supports structured outputs |
| `PROMPT_HINTS` | empty | Extra rules for your family, e.g. "Pastizzi go in Bakery" |
| `POLL_INTERVAL` | `60` | Seconds between checks |
| `DRY_RUN` | `false` | Log the proposed tags without saving them |
| `RUN_ONCE` | `false` | Do one pass and exit (useful with cron) |
| `LOG_LEVEL` | `INFO` | `DEBUG` for more detail |

## Notes

- If the list isn't found, the log prints the names of all lists the user can see.
- To re-tag an item, remove its tag in the Tasks app and it will be picked up on the next pass.
- A shared family list works too: use the account the list belongs to, or any account it's shared with.
