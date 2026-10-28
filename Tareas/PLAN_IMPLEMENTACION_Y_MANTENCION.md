# Plan de implementación y mantención de LogiVisir

## 1. Objetivo

Establecer las acciones necesarias para mantener LogiVisir disponible, respaldado y operativo durante su utilización. Este plan considera la aplicación web, el código fuente, la base de datos y el servicio de alojamiento.

## 2. Disponibilidad del sistema

LogiVisir se encuentra publicado como aplicación web y puede ser utilizado mediante la siguiente dirección:

https://logivisir.pythonanywhere.com

La disponibilidad del sistema depende principalmente de los siguientes componentes:

- Aplicación web desarrollada con Django.
- Servicio de alojamiento PythonAnywhere.
- Base de datos configurada para el proyecto.
- Repositorio de código almacenado en Azure Repos.
- Conexión a Internet de los usuarios.

## 3. Control y supervisión

El equipo debe comprobar periódicamente:

- Que la página principal cargue correctamente.
- Que el inicio y cierre de sesión funcionen.
- Que los usuarios puedan acceder según su rol.
- Que las funciones de clientes, pedidos, rutas y entregas estén disponibles.
- Que no existan errores visibles en la aplicación.
- Que el servicio de alojamiento se encuentre activo.

## 4. Respaldo de la información

Para reducir el riesgo de pérdida de información se utilizarán los siguientes mecanismos:

- El código fuente permanecerá respaldado en Azure Repos.
- Cada integrante deberá realizar commits con su nombre y correo configurados.
- Los cambios deberán vincularse con Azure Boards utilizando `AB#`.
- Antes de realizar modificaciones importantes se deberá actualizar el repositorio mediante `git pull`.
- Se deberán realizar respaldos periódicos de la base de datos.
- No se deberán almacenar contraseñas ni credenciales privadas directamente en el repositorio.

## 5. Continuidad frente a fallas

Si la aplicación deja de funcionar, se aplicará el siguiente procedimiento:

1. Comprobar el acceso a PythonAnywhere.
2. Revisar los registros de errores de la aplicación.
3. Verificar las variables de entorno y la conexión con la base de datos.
4. Identificar el último cambio realizado en Azure Repos.
5. Corregir el error o restaurar una versión estable.
6. Probar nuevamente el inicio de sesión y las funciones principales.
7. Registrar la solución mediante un commit vinculado con la tarea correspondiente.

## 6. Responsables

- Ignacio Villalobos: coordinación técnica, Azure DevOps y verificación general.
- Alejandro Campos: revisión de interfaz y funcionamiento del frontend.
- Patricio Sánchez: revisión del backend y conexión con los datos.

## 7. Resultado esperado

Con estas medidas, LogiVisir contará con respaldo del código, trazabilidad de los cambios y un procedimiento básico de recuperación ante fallas, permitiendo mantener la continuidad del servicio.


## 8. Plan de mantención

La mantención de LogiVisir permitirá conservar la estabilidad, seguridad y correcto funcionamiento de la aplicación después de su implementación.

### 8.1 Mantención preventiva

Se realizarán las siguientes actividades:

- Revisar periódicamente el funcionamiento de la aplicación.
- Comprobar el acceso de los usuarios y sus roles.
- Verificar las funciones de clientes, pedidos, rutas y entregas.
- Mantener actualizadas las dependencias del proyecto.
- Revisar el uso de almacenamiento y la base de datos.
- Realizar respaldos periódicos del código y los datos.

### 8.2 Mantención correctiva

Cuando se detecte un problema se deberá:

1. Registrar el error encontrado.
2. Identificar los archivos o componentes afectados.
3. Realizar la corrección en un entorno controlado.
4. Probar la funcionalidad modificada.
5. Registrar el cambio mediante un commit vinculado a Azure Boards.
6. Verificar nuevamente la aplicación publicada.

### 8.3 Frecuencia

- Revisión funcional: semanal.
- Revisión de errores: cada vez que se reporte una incidencia.
- Actualización de dependencias: mensual.
- Respaldo del código: con cada cambio mediante Azure Repos.
- Respaldo de datos: semanal o antes de una modificación importante.

### 8.4 Registro de cambios

Todos los cambios deberán quedar registrados en Azure, indicando una descripción clara y el número de la tarea correspondiente.