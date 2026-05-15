@echo off
REM SheetPilot - Execucao headless para Windows Task Scheduler
REM Uso: agendar no Task Scheduler para rodar diariamente
REM
REM 1. Abra o Task Scheduler
REM 2. Criar tarefa basica
REM 3. Acionador: "Diariamente" ou "Ao iniciar"
REM 4. Acao: "Iniciar um programa"
REM    Programa: C:\caminho\para\run_pipeline.bat
REM    Iniciar em: C:\Users\usuario\Desktop\Projetos IA\sheetpilot_pilot

cd /d "%~dp0"

set DB_PATH=%USERPROFILE%\sheetpilot_db\pilot.db
set MIGRATIONS=migrations
set DATA_DIR=C:\caminho\para\planilhas

echo [%DATE% %TIME%] Iniciando pipeline SheetPilot >> pipeline_log.txt

REM Pipeline completo (scan + ingest + transform)
python main.py --cli full-pipeline --db "%DB_PATH%" --migrations "%MIGRATIONS%" >> pipeline_log.txt 2>&1

REM Exportar como xlsx
python main.py --cli export --db "%DB_PATH%" >> pipeline_log.txt 2>&1

echo [%DATE% %TIME%] Pipeline concluido >> pipeline_log.txt
