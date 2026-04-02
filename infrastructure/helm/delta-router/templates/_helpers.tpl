{{/*
Chart name.
*/}}
{{- define "delta-router.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}
{{/*
Fully qualified app name (release-prefixed).
*/}}
{{- define "delta-router.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}
{{/*
Common labels applied to all resources.
*/}}
{{- define "delta-router.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
{{/*
Per-service fullnames.
*/}}
{{- define "delta-router.routingService.fullname" -}}
{{- printf "%s-%s" (include "delta-router.fullname" .) "routing-service" | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- define "delta-router.webUi.fullname" -}}
{{- printf "%s-%s" (include "delta-router.fullname" .) "web-ui" | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- define "delta-router.duckdbWorker.fullname" -}}
{{- printf "%s-%s" (include "delta-router.fullname" .) "duckdb-worker" | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- define "delta-router.postgresql.fullname" -}}
{{- printf "%s-%s" (include "delta-router.fullname" .) "postgresql" | trunc 63 | trimSuffix "-" }}
{{- end }}