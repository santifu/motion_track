import bpy
import bmesh
import json
import asyncio
import websockets
import threading
from mathutils import Vector
import time

class ObjectTrackingReceiver:
    def __init__(self):
        self.tracking_objects = {}
        self.is_running = False
        self.websocket_server = None
        self.server_thread = None
        
    def create_tracking_object(self, label):
        """Crea un objeto en Blender para rastrear las coordenadas"""
        # Crear una esfera para representar el objeto
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(0, 0, 0))
        obj = bpy.context.active_object
        obj.name = f"Tracked_{label}"
        
        # Crear material de color único para cada tipo de objeto
        mat = bpy.data.materials.new(name=f"Mat_{label}")
        mat.use_nodes = True
        
        # Colores diferentes para diferentes objetos
        colors = {
            'person': (1, 0, 0, 1),      # Rojo
            'car': (0, 1, 0, 1),         # Verde
            'bicycle': (0, 0, 1, 1),     # Azul
            'dog': (1, 1, 0, 1),         # Amarillo
            'cat': (1, 0, 1, 1),         # Magenta
            'bird': (0, 1, 1, 1),        # Cian
        }
        
        color = colors.get(label, (0.5, 0.5, 0.5, 1))  # Gris por defecto
        mat.node_tree.nodes["Principled BSDF"].inputs[0].default_value = color
        
        obj.data.materials.append(mat)
        
        # Añadir una cola (trail) usando un sistema de partículas
        bpy.ops.object.modifier_add(type='PARTICLE_SYSTEM')
        psys = obj.particle_systems[0]
        psys.settings.count = 100
        psys.settings.frame_start = 1
        psys.settings.frame_end = 250
        psys.settings.lifetime = 50
        psys.settings.emit_from = 'VERT'
        psys.settings.physics_type = 'NO'
        psys.settings.render_type = 'OBJECT'
        
        # Crear objeto pequeño para las partículas
        bpy.ops.mesh.primitive_cube_add(size=0.05, location=(10, 10, 10))
        particle_obj = bpy.context.active_object
        particle_obj.name = f"Particle_{label}"
        psys.settings.render_object = particle_obj
        
        # Seleccionar el objeto principal de nuevo
        bpy.context.view_layer.objects.active = obj
        
        return obj
    
    def update_object_position(self, label, x, y, z, confidence):
        """Actualiza la posición del objeto en Blender"""
        if label not in self.tracking_objects:
            self.tracking_objects[label] = self.create_tracking_object(label)
        
        obj = self.tracking_objects[label]
        obj.location = Vector((x, y, z))
        
        # Escalar el objeto basado en la confianza
        scale = 0.5 + (confidence * 0.5)  # Escala entre 0.5 y 1.0
        obj.scale = Vector((scale, scale, scale))
        
        # Añadir keyframe para animación
        frame = bpy.context.scene.frame_current
        obj.keyframe_insert(data_path="location", frame=frame)
        obj.keyframe_insert(data_path="scale", frame=frame)
        
        print(f"Updated {label} at ({x:.3f}, {y:.3f}, {z:.3f}) with confidence {confidence:.3f}")
    
    async def handle_websocket_message(self, websocket, path):
        """Maneja los mensajes entrantes del WebSocket"""
        print(f"Client connected: {websocket.remote_address}")
        
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    
                    # Extraer información del mensaje
                    label = data.get('label', 'unknown')
                    confidence = data.get('confidence', 0.0)
                    coords = data.get('coordinates', {})
                    
                    x = coords.get('x', 0)
                    y = coords.get('y', 0)
                    z = coords.get('z', 0)
                    
                    # Actualizar el objeto en Blender
                    # Nota: Esto debe ejecutarse en el hilo principal de Blender
                    bpy.app.timers.register(
                        lambda: self.update_object_position(label, x, y, z, confidence),
                        first_interval=0.0
                    )
                    
                except json.JSONDecodeError:
                    print(f"Error parsing JSON: {message}")
                except Exception as e:
                    print(f"Error processing message: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            print(f"Client disconnected: {websocket.remote_address}")
        except Exception as e:
            print(f"WebSocket error: {e}")
    
    def start_server(self, host='localhost', port=8765):
        """Inicia el servidor WebSocket"""
        if self.is_running:
            print("Server is already running")
            return
        
        self.is_running = True
        
        # Crear un nuevo bucle de eventos para el hilo del servidor
        def run_server():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            start_server = websockets.serve(
                self.handle_websocket_message,
                host,
                port
            )
            
            print(f"WebSocket server started on ws://{host}:{port}")
            loop.run_until_complete(start_server)
            loop.run_forever()
        
        # Ejecutar el servidor en un hilo separado
        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()
    
    def stop_server(self):
        """Detiene el servidor WebSocket"""
        self.is_running = False
        if self.server_thread:
            self.server_thread.join(timeout=1)
        print("WebSocket server stopped")
    
    def clear_tracking_objects(self):
        """Limpia todos los objetos de rastreo"""
        for label, obj in self.tracking_objects.items():
            # Eliminar el objeto de partículas también
            particle_obj_name = f"Particle_{label}"
            if particle_obj_name in bpy.data.objects:
                bpy.data.objects.remove(bpy.data.objects[particle_obj_name])
            
            # Eliminar el objeto principal
            bpy.data.objects.remove(obj)
        
        self.tracking_objects.clear()
        print("All tracking objects cleared")

# Crear instancia global del receptor
tracker = ObjectTrackingReceiver()

# Operadores de Blender para controlar el sistema
class OBJECT_OT_start_tracking(bpy.types.Operator):
    """Inicia el servidor de rastreo WebSocket"""
    bl_idname = "object.start_tracking"
    bl_label = "Start Object Tracking"
    
    def execute(self, context):
        tracker.start_server()
        self.report({'INFO'}, "Object tracking started on ws://localhost:8765")
        return {'FINISHED'}

class OBJECT_OT_stop_tracking(bpy.types.Operator):
    """Detiene el servidor de rastreo WebSocket"""
    bl_idname = "object.stop_tracking"
    bl_label = "Stop Object Tracking"
    
    def execute(self, context):
        tracker.stop_server()
        self.report({'INFO'}, "Object tracking stopped")
        return {'FINISHED'}

class OBJECT_OT_clear_tracking(bpy.types.Operator):
    """Limpia todos los objetos de rastreo"""
    bl_idname = "object.clear_tracking"
    bl_label = "Clear Tracking Objects"
    
    def execute(self, context):
        tracker.clear_tracking_objects()
        self.report({'INFO'}, "All tracking objects cleared")
        return {'FINISHED'}

# Panel de interfaz de usuario
class OBJECT_PT_tracking_panel(bpy.types.Panel):
    """Panel de control para el rastreo de objetos"""
    bl_label = "Object Tracking WebSocket"
    bl_idname = "OBJECT_PT_tracking_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Object Tracking'
    
    def draw(self, context):
        layout = self.layout
        
        layout.label(text="WebSocket Object Tracking")
        layout.separator()
        
        row = layout.row()
        row.operator("object.start_tracking", text="Start Tracking")
        row.operator("object.stop_tracking", text="Stop Tracking")
        
        layout.separator()
        layout.operator("object.clear_tracking", text="Clear All Objects")
        
        layout.separator()
        layout.label(text="Instructions:")
        layout.label(text="1. Click 'Start Tracking'")
        layout.label(text="2. Open the web app")
        layout.label(text="3. Connect to ws://localhost:8765")
        layout.label(text="4. Select objects to track")

# Registrar clases
classes = [
    OBJECT_OT_start_tracking,
    OBJECT_OT_stop_tracking,
    OBJECT_OT_clear_tracking,
    OBJECT_PT_tracking_panel
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)
    
    # Detener el servidor al desregistrar
    tracker.stop_server()

if __name__ == "__main__":
    register()
    
    # Iniciar automáticamente el servidor
    tracker.start_server()
    print("Object tracking system ready!")