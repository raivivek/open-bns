# Local venv when present (needed for PDF extraction); plain python3 otherwise,
# e.g. on the Cloudflare Pages build image (site/data/test need only the stdlib).
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PAGES_PROJECT ?= bns-in

.PHONY: all setup pages textlayer reconcile data site serve test deploy clean

all: reconcile data site

setup:
	uv venv -q .venv
	uv pip install -q --python .venv pymupdf

# Page images for the independent image transcription (ocr/pages, see ocr/SPEC.md).
pages:
	$(PY) -m bns.render_pages

textlayer:
	$(PY) -m bns.textlayer

# Fails if the text layer and the image transcription disagree anywhere that
# has not been adjudicated in ocr/accepted.json.
reconcile: textlayer
	$(PY) -m bns.reconcile --strict

data:
	$(PY) -m bns.parse

site:
	$(PY) -m bns.site

serve: site
	$(PY) -m http.server -d dist 8000

test:
	$(PY) -m unittest discover -s tests -t .
	node --test tests/

# Direct upload to Cloudflare Pages (project/output from wrangler.toml).
deploy: test site
	npx wrangler@4 pages deploy dist --project-name $(PAGES_PROJECT) --branch main

clean:
	rm -rf build dist
