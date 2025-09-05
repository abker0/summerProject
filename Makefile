HOST ?= 127.0.0.1
PORT ?= 5000
PY ?= python3

.PHONY: run stop clean-db new-coach-token seed-coaches reset gen-past

run:
	@if [ -f .flask.pid ] && kill -0 $$(cat .flask.pid) 2>/dev/null; then \
	  echo "Server already running (PID $$(cat .flask.pid))"; \
	else \
	  echo "Starting server..."; \
	  nohup $(PY) main.py > .flask.out 2>&1 & echo $$! > .flask.pid; \
	  printf "Waiting for http://$(HOST):$(PORT)"; \
	  for i in $$(seq 1 100); do \
	    sleep 0.1; \
	    if curl -s -o /dev/null http://$(HOST):$(PORT)/; then echo " - ready"; break; fi; \
	    printf "."; \
	  done; \
	fi

stop:
	@if [ -f .flask.pid ]; then \
	  PID=$$(cat .flask.pid); \
	  echo "Stopping server PID $$PID"; \
	  kill $$PID 2>/dev/null || true; \
	  rm -f .flask.pid; \
	else \
	  echo "No running server"; \
	fi

clean-db:
	@rm -f app.db && echo "Removed app.db" || true

new-coach-token:
	@$(PY) main.py -new_coach | awk -F'token=' '/token=/{print $$2}'

seed-coaches: run
	@SUFFIX=$$(date +%s); \
	for i in 1 2 3 4 5; do \
	  TOKEN=$$($(PY) main.py -new_coach | awk -F'token=' '/token=/{print $$2}'); \
	  if [ -z "$$TOKEN" ]; then echo "Failed to generate invite token"; exit 1; fi; \
	  EMAIL="coach$$i+$$SUFFIX@example.com"; \
	  CODE=$$(curl -s -o /dev/null -w "%{http_code}\n" -X POST http://$(HOST):$(PORT)/register/coach \
	    -H 'Content-Type: application/x-www-form-urlencoded' \
	    --data-urlencode invite_token="$$TOKEN" \
	    --data-urlencode title="Mr" \
	    --data-urlencode first_name="Coach$$i" \
	    --data-urlencode last_name="Test" \
	    --data-urlencode email="$$EMAIL" \
	    --data-urlencode password="Pass1234!" \
	    --data-urlencode confirm="Pass1234!" \
	    --data-urlencode phone="070000000$$i" ); \
	  if echo "$$CODE" | grep -qE '^(200|302)$$'; then \
	    echo "Created coach: $$EMAIL"; \
	  else \
	    echo "Registration failed for $$EMAIL (HTTP $$CODE)"; exit 1; \
	  fi; \
	done

reset: stop clean-db run seed-coaches

# Generate past classes for an email (learner or coach)
gen-past:
	@if [ -z "$(email)" ]; then echo "Usage: make gen-past email=user@example.com [weeks=3] [count=3]"; exit 2; fi
	@weeks=$${weeks:-3}; count=$${count:-3}; \
	$(PY) main.py -gen_past_for $(email) -weeks $$weeks -count $$count
