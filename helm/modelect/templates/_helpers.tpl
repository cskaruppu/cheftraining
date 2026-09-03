{{- define "modelect.labels" -}}
app.kubernetes.io/part-of: modelect
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "modelect.apiImage" -}}
{{ .Values.image.registry }}/{{ required "image.namespace is required (your quay.io user/org)" .Values.image.namespace }}/{{ .Values.image.apiRepository }}:{{ .Values.image.tag }}
{{- end }}

{{- define "modelect.uiImage" -}}
{{ .Values.image.registry }}/{{ required "image.namespace is required (your quay.io user/org)" .Values.image.namespace }}/{{ .Values.image.uiRepository }}:{{ .Values.image.tag }}
{{- end }}

{{- define "modelect.agentImage" -}}
{{ .Values.image.registry }}/{{ required "image.namespace is required (your quay.io user/org)" .Values.image.namespace }}/{{ .Values.image.agentRepository }}:{{ .Values.image.tag }}
{{- end }}
