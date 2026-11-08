# Presentación de KPI – LogiVisir EF2

## Objetivo de la demostración
Presentar el funcionamiento de LogiVisir y demostrar cómo facilita la gestión de clientes, pedidos, rutas y entregas.

## KPI considerados

### KPI 1: Distancia diaria recorrida
Permite comparar los kilómetros recorridos antes y después de utilizar LogiVisir.

### KPI 2: Entregas completadas
Mide la cantidad y el porcentaje de pedidos entregados correctamente.

### KPI 3: Tiempo de preparación de rutas
Mide el tiempo necesario para crear y asignar una ruta de reparto.

### KPI 4: Pedidos pendientes
Permite visualizar cuántos pedidos continúan pendientes durante la jornada.

## Demostración
1. Iniciar sesión.
2. Registrar o seleccionar clientes.
3. Crear un pedido.
4. Crear una ruta y asignar un chofer.
5. Revisar las paradas.
6. Marcar una entrega.
7. Visualizar el estado actualizado del pedido.


## Checklist de prueba de humo

Se preparó una revisión rápida de las funciones principales de LogiVisir para comprobar que la plataforma se encuentre operativa antes de la entrega final.

- [ ] La página de inicio carga correctamente.
- [ ] El usuario puede iniciar sesión.
- [ ] Se visualiza el listado de clientes.
- [ ] Se puede registrar y consultar un pedido.
- [ ] Se puede crear una ruta de reparto.
- [ ] Se puede asignar un chofer a una ruta.
- [ ] Las paradas aparecen correctamente en el mapa.
- [ ] Se puede actualizar el estado de una entrega.
- [ ] Los mensajes de validación se muestran correctamente.
- [ ] La sesión se puede cerrar sin errores.

### Resultado

Las pruebas se ejecutarán en la versión publicada de LogiVisir. Cada función aprobada será marcada en este checklist y cualquier error encontrado será registrado para su corrección

## Pruebas de humo de LogiVisir

- [ ] La página principal carga correctamente.
- [ ] El usuario puede iniciar sesión.
- [ ] Se visualiza el listado de clientes.
- [ ] Se puede registrar un pedido.
- [ ] Los campos incompletos muestran mensajes de validación.
- [ ] Se puede crear una ruta y asignar un chofer.
- [ ] Las paradas se visualizan correctamente en el mapa.
- [ ] Se puede marcar una entrega como completada.
- [ ] El usuario puede cerrar sesión.
- [ ] Una URL inexistente muestra la página de error 404.

Resultado esperado: las funciones principales deben operar sin errores críticos antes de la entrega final.

Realizar pruebas de humo para verificar que cada usuario pueda acceder únicamente a las funciones correspondientes a su rol.

## Casos de prueba

- [ ] El administrador puede acceder al panel administrativo.
- [ ] El administrador puede consultar clientes, pedidos, rutas y choferes.
- [ ] El chofer puede visualizar únicamente sus rutas asignadas.
- [ ] Un usuario sin iniciar sesión es redirigido al inicio de sesión.
- [ ] Un chofer no puede ingresar al panel administrativo mediante la URL.
- [ ] Los usuarios de una empresa no pueden visualizar información de otra empresa.
- [ ] Después de cerrar sesión no se puede volver a una página privada.

## Resultado esperado

Los permisos deben impedir accesos no autorizados y proteger la información de cada empresa.

## Pruebas de direcciones y mapa

Se realizarán pruebas para comprobar que las direcciones ingresadas sean procesadas correctamente y que las paradas se visualicen en el mapa de LogiVisir.

### Casos de prueba

- [ ] Una dirección válida puede registrarse correctamente.
- [ ] La dirección registrada aparece asociada al cliente correspondiente.
- [ ] Una dirección incompleta muestra un mensaje de validación.
- [ ] La plataforma evita guardar una dirección vacía.
- [ ] Las direcciones de las paradas aparecen correctamente en el mapa.
- [ ] Cada marcador del mapa corresponde a una parada de la ruta.
- [ ] La información del cliente se muestra al seleccionar una parada.
- [ ] El enlace de navegación utiliza la dirección correcta.
- [ ] La ruta mantiene el orden establecido de las paradas.
- [ ] Una dirección no encontrada muestra un mensaje comprensible.

### Resultado esperado

Las direcciones deben registrarse sin errores, relacionarse con el cliente correspondiente y visualizarse correctamente como paradas dentro del mapa.