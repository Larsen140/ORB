@echo off
rem Richtet einmalig die Admin-Aufgabe ein, damit ORB die Acer-Nitro-Tastatur einfaerben kann.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%~dp0tastatur.ps1','-Einrichten'"
