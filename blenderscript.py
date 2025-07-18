import bpy
import json
import asyncio
import websockets
import threading
from mathutils import Vector

class ObjectTrackingReceiver:
    def __init__(self):
        self.tracking_objects = {}
        self.is_running = False
        self.websocket_server = None
        self.server_thread = None
        self.visible_objects = {}
        
    def create_tracking_object(self, label):
        """Crea un objeto en Blender para rastrear las coordenadas"""
        # Crear una esfera para representar el objeto
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(0, 0, 0))
        obj = bpy.context.active_object
        obj.name = f"Tracked_{label}"
        obj.hide_render = True
        obj.hide_viewport = True
        
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
            'cup': (1, 0.5, 0, 1),       # Naranja
            'book': (0.5, 0.25, 0, 1),   # Marrón
            'laptop': (0, 0.5, 0.5, 1),  # Verde azulado
            'cell phone': (0.8, 0.6, 0.9, 1)  # Lila
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
        particle_obj.hide_render = True
        particle_obj.hide_viewport = True
        psys.settings.render_object = particle_obj
        
        # Seleccionar el objeto principal de nuevo
        bpy.context.view_layer.objects.active = obj
        
        return obj
    
    def update_object_position(self, label, x, y, z, confidence):
        """Actualiza la posición del objeto en Blender"""
        if label not in self.tracking_objects:
            self.tracking_objects[label] = self.create_tracking_object(label)
            self.visible_objects[label] = False
        
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
    
    def set_object_visibility(self, label, visible):
        """Controla la visibilidad de un objeto"""
        if label in self.tracking_objects:
            obj = self.tracking_objects[label]
            obj.hide_viewport = not visible
            obj.hide_render = not visible
            
            # Mostrar u ocultar también las partículas
            particle_name = f"Particle_{label}"
            if particle_name in bpy.data.objects:
                bpy.data.objects[particle_name].hide_viewport = not visible
                bpy.data.objects[particle_name].hide_render = not visible
            
            self.visible_objects[label] = visible
            print(f"{label} visibility set to: {visible}")
    
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
                    visible = data.get('visible', True)
                    
                    x = coords.get('x', 0)
                    y = coords.get('y', 0)
                    z = coords.get('z', 0)
                    
                    # Actualizar visibilidad
                    bpy.app.timers.register(
                        lambda: self.set_object_visibility(label, visible),
                        first_interval=0.0
                    )
                    
                    # Actualizar posición solo si es visible
                    if visible:
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
    
    def start_server(self, host='localhost', port=8333):
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
        self.visible_objects.clear()
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
        self.report({'INFO'}, "Object tracking started on ws://localhost:8333")
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

class OBJECT_OT_toggle_object_visibility(bpy.types.Operator):
    """Alterna la visibilidad de un objeto específico"""
    bl_idname = "object.toggle_visibility"
    bl_label = "Toggle Object Visibility"
    bl_options = {'REGISTER', 'UNDO'}
    
    label: bpy.props.StringProperty(name="Label", default="")
    
    def execute(self, context):
        if self.label in tracker.visible_objects:
            new_visibility = not tracker.visible_objects[self.label]
            tracker.set_object_visibility(self.label, new_visibility)
            self.report({'INFO'}, f"Visibility for {self.label} set to {new_visibility}")
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
        
        # Estado del servidor
        status_text = "RUNNING" if tracker.is_running else "STOPPED"
        status_icon = 'PLAY' if tracker.is_running else 'PAUSE'
        layout.label(text=f"Server Status: {status_text}", icon=status_icon)
        
        layout.separator()
        
        # Controles principales
        row = layout.row()
        if not tracker.is_running:
            row.operator("object.start_tracking", text="Start Tracking", icon='PLAY')
        else:
            row.operator("object.stop_tracking", text="Stop Tracking", icon='PAUSE')
        
        row.operator("object.clear_tracking", text="Clear All", icon='TRASH')
        
        # Lista de objetos detectados
        if tracker.tracking_objects:
            layout.separator()
            layout.label(text="Detected Objects:", icon='OBJECT_DATA')
            
            for label, obj in tracker.tracking_objects.items():
                box = layout.box()
                row = box.row()
                
                # Nombre y visibilidad
                visibility = tracker.visible_objects.get(label, False)
                visibility_icon = 'HIDE_OFF' if visibility else 'HIDE_ON'
                row.label(text=f"● {label}", icon=visibility_icon)
                
                # Botón para alternar visibilidad
                op = row.operator("object.toggle_visibility", text="Toggle")
                op.label = label
                
                # Información adicional
                if visibility:
                    box.label(text=f"Position: ({obj.location.x:.2f}, {obj.location.y:.2f}, {obj.location.z:.2f})")
                    box.label(text=f"Scale: {obj.scale.x:.2f}")
        
        # Instrucciones
        layout.separator()
        layout.label(text="Instructions:", icon='INFO')
        layout.label(text="1. Click 'Start Tracking'")
        layout.label(text="2. Open the web app")
        layout.label(text="3. Connect to ws://localhost:8333")
        layout.label(text="4. Select objects to track")
        layout.label(text="5. Objects will appear when detected")

# Registrar clases
classes = [
    OBJECT_OT_start_tracking,
    OBJECT_OT_stop_tracking,
    OBJECT_OT_clear_tracking,
    OBJECT_OT_toggle_object_visibility,
    OBJECT_PT_tracking_panel
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    # Iniciar automáticamente el servidor
    tracker.start_server()
    print("Object tracking system ready! Objects will appear when detected.")

def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)
    
    # Detener el servidor al desregistrar
    tracker.stop_server()

if __name__ == "__main__":
    register()