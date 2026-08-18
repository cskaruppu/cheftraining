FROM python:3.12-slim
WORKDIR /opt/agent
COPY agent.py .
# stdlib only — no dependencies to install
RUN chgrp -R 0 /opt/agent && chmod -R g=u /opt/agent
USER 1001
CMD ["python", "-u", "agent.py"]
