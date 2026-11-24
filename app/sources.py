# (source, board slug). The slug is the company's name in its public job-board URL.
# Some slugs may be wrong or dead. That is fine: the ingest script skips failures.
BOARDS = [
    # Greenhouse
    ("greenhouse", "airbnb"), ("greenhouse", "stripe"), ("greenhouse", "databricks"),
    ("greenhouse", "cloudflare"), ("greenhouse", "datadog"), ("greenhouse", "coinbase"),
    ("greenhouse", "reddit"), ("greenhouse", "pinterest"), ("greenhouse", "discord"),
    ("greenhouse", "figma"), ("greenhouse", "instacart"), ("greenhouse", "lyft"),
    ("greenhouse", "gitlab"), ("greenhouse", "twilio"), ("greenhouse", "asana"),
    ("greenhouse", "dropbox"), ("greenhouse", "mongodb"), ("greenhouse", "elastic"),
    ("greenhouse", "okta"), ("greenhouse", "samsara"), ("greenhouse", "anthropic"),
    ("greenhouse", "brex"), ("greenhouse", "robinhood"), ("greenhouse", "scaleai"),
    ("greenhouse", "airtable"), ("greenhouse", "webflow"), ("greenhouse", "vercel"),
    ("greenhouse", "postman"),
    # Lever
    ("lever", "spotify"), ("lever", "palantir"), ("lever", "plaid"),
    ("lever", "cred"), ("lever", "meesho"), ("lever", "paytm"),
    ("lever", "whoop"), ("lever", "mistral"),
    # Ashby
    ("ashby", "openai"), ("ashby", "notion"), ("ashby", "ramp"),
    ("ashby", "linear"), ("ashby", "supabase"), ("ashby", "posthog"),
    ("ashby", "replit"), ("ashby", "deel"), ("ashby", "sierra"),
    ("ashby", "cohere"), ("ashby", "zapier"),
]