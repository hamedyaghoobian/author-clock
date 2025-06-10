import tkinter as tk
from tkinter import font as tkFont
from datetime import datetime
from zoneinfo import ZoneInfo
import inflect
from langchain_ollama import OllamaLLM
import random
import math
import colorsys

class JetsonDisplayClock:
    def __init__(self):
        # Initialize Ollama connection
        self.ollama = OllamaLLM(
            base_url='http://localhost:11434', 
            model="gemma3:4b", 
            temperature=0.3, 
            num_predict=80
        )
        
        # Setup main window
        self.root = tk.Tk()
        self.setup_window()
        self.setup_responsive_design()
        self.create_layout()
        
        # Animation variables
        self.animation_frame = 0
        self.hue_shift = 0
        self.last_minute = -1
        
        # Start systems
        self.start_ambient_animation()
        self.update_time()
        
    def setup_window(self):
        """Configure window for installation display"""
        self.root.title("Temporal Installation")
        
        # Fullscreen for public display (disabled for testing)
        # self.root.attributes('-fullscreen', True)
        self.root.geometry("1200x800")  # Default window size for testing
        self.root.configure(bg='#000000')
        # self.root.config(cursor="none")
        
        # Control keys
        self.root.bind('<Escape>', lambda e: self.root.quit())
        self.root.bind('<space>', self.force_update)
        self.root.bind('<Configure>', self.on_window_resize)
        
    def setup_responsive_design(self):
        """Calculate responsive sizing"""
        self.screen_width = self.root.winfo_width() or self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_height() or self.root.winfo_screenheight()
        
        # Base unit for responsive design
        self.unit = min(self.screen_width, self.screen_height) // 40
        
        # Font hierarchy
        self.fonts = {
            'massive': ('Helvetica Neue', int(self.unit * 3), 'bold'),
            'large': ('Helvetica Neue', int(self.unit * 2), 'normal'),
            'medium': ('Georgia', int(self.unit * 1.2), 'normal'),
            'small': ('Helvetica Neue', int(self.unit * 0.8), 'normal'),
            'tiny': ('Helvetica Neue', int(self.unit * 0.5), 'normal')
        }
        
        # Color palette
        self.colors = {
            'bg': '#000000',
            'text_primary': '#ffffff',
            'text_secondary': '#cccccc',
            'text_subtle': '#666666',
            'accent_time': '#00ff88',
            'accent_warm': '#ff6b35',
            'accent_cool': '#4ecdc4'
        }
    
    def on_window_resize(self, event=None):
        """Handle window resize events"""
        # Only respond to root window resize events
        if event and event.widget != self.root:
            return
            
        # Recalculate responsive design
        self.setup_responsive_design()
        
        # Update canvas size
        if hasattr(self, 'canvas'):
            self.canvas.configure(width=self.screen_width, height=self.screen_height)
            
        # Update layout positioning
        self.update_layout_positioning()
        
        # Update font styling
        if hasattr(self, 'narrative_text'):
            self.update_text_styling()
    
    def update_layout_positioning(self):
        """Update widget positions based on new dimensions"""
        if hasattr(self, 'header'):
            self.header.configure(font=self.fonts['tiny'])
            self.header.place(x=self.unit, y=self.unit//2)
            
        if hasattr(self, 'digital_time'):
            self.digital_time.configure(font=self.fonts['small'])
            self.digital_time.place(x=self.unit, y=self.unit*2)
            
        if hasattr(self, 'narrative_text'):
            self.narrative_text.configure(
                font=self.fonts['medium'],
                padx=self.unit*2,
                pady=self.unit
            )
            
            # Recenter the narrative
            text_width = self.screen_width - (self.unit * 6)
            text_height = self.screen_height // 3
            self.narrative_text.place(
                x=self.unit*3,
                y=(self.screen_height - text_height) // 2,
                width=text_width,
                height=text_height
            )
            
        if hasattr(self, 'footer'):
            self.footer.configure(font=self.fonts['tiny'])
            self.footer.place(
                x=self.unit,
                y=self.screen_height - self.unit*2
            )
        
    def create_layout(self):
        """Create sophisticated layout"""
        # Background canvas for animations
        self.canvas = tk.Canvas(
            self.root,
            bg=self.colors['bg'],
            highlightthickness=0,
            width=self.screen_width,
            height=self.screen_height
        )
        self.canvas.pack(fill='both', expand=True)
        
        # Overlay frame for text
        self.overlay = tk.Frame(self.root, bg=self.colors['bg'])
        self.overlay.place(x=0, y=0, relwidth=1, relheight=1)
        
        # Header
        self.header = tk.Label(
            self.overlay,
            text="TEMPORAL CONSCIOUSNESS",
            font=self.fonts['tiny'],
            fg=self.colors['text_subtle'],
            bg=self.colors['bg']
        )
        self.header.place(x=self.unit, y=self.unit//2)
        
        # Digital time reference
        self.digital_time = tk.Label(
            self.overlay,
            text="",
            font=self.fonts['small'],
            fg=self.colors['text_subtle'],
            bg=self.colors['bg']
        )
        self.digital_time.place(x=self.unit, y=self.unit*2)
        
        # Main narrative area
        self.narrative_text = tk.Text(
            self.overlay,
            font=self.fonts['medium'],
            fg=self.colors['text_primary'],
            bg=self.colors['bg'],
            bd=0,
            highlightthickness=0,
            wrap='word',
            state='disabled',
            padx=self.unit*2,
            pady=self.unit
        )
        
        # Center the narrative
        text_width = self.screen_width - (self.unit * 6)
        text_height = self.screen_height // 3
        self.narrative_text.place(
            x=self.unit*3,
            y=(self.screen_height - text_height) // 2,
            width=text_width,
            height=text_height
        )
        
        # Configure text tags
        self.setup_text_styling()
        
        # Footer
        self.footer = tk.Label(
            self.overlay,
            text="◦ temporal installation ◦",
            font=self.fonts['tiny'],
            fg=self.colors['text_subtle'],
            bg=self.colors['bg']
        )
        self.footer.place(
            x=self.unit,
            y=self.screen_height - self.unit*2
        )
        
    def setup_text_styling(self):
        """Configure advanced text styling"""
        self.update_text_styling()
    
    def update_text_styling(self):
        """Update text styling with current responsive units"""
        if hasattr(self, 'narrative_text'):
            self.narrative_text.tag_configure(
                "time_highlight",
                foreground=self.colors['accent_time'],
                font=('Georgia', int(self.unit * 1.2), 'bold')  # Same font family, just bold
            )
            
            self.narrative_text.tag_configure(
                "emphasis",
                foreground=self.colors['accent_warm'],
                font=('Georgia', int(self.unit * 1.2), 'italic')
            )
        
    def time_in_words(self, hour, minute):
        """Enhanced time to words conversion"""
        p = inflect.engine()
        
        # Special poetic cases
        if minute == 0:
            if hour == 0 or hour == 24:
                return "midnight"
            elif hour == 12:
                return "noon"
            else:
                return f"{p.number_to_words(hour)} o'clock"
        elif minute == 15:
            return f"quarter past {p.number_to_words(hour)}"
        elif minute == 30:
            return f"half past {p.number_to_words(hour)}"
        elif minute == 45:
            return f"quarter to {p.number_to_words((hour + 1) % 24)}"
        elif minute <= 30:
            return f"{p.number_to_words(minute)} past {p.number_to_words(hour)}"
        else:
            return f"{p.number_to_words(60 - minute)} to {p.number_to_words((hour + 1) % 24)}"
    
    def generate_installation_narrative(self, time_words, am_pm, hour):
        """Generate narratives for installation context"""
        
        # Time-of-day contexts
        contexts = {
            (5, 9): "morning awakening",
            (9, 12): "productive hours", 
            (12, 14): "midday pause",
            (14, 17): "afternoon flow",
            (17, 20): "evening transition",
            (20, 23): "night contemplation",
            (23, 5): "liminal hours"
        }
        
        context = "temporal moment"
        for (start, end), ctx in contexts.items():
            if start <= hour < end:
                context = ctx
                break
                
        prompts = [
            f"Write a contemplative sentence about {context} at {time_words} {am_pm}. Focus on the feeling of this moment.",
            f"Create a poetic observation about consciousness and time at {time_words} {am_pm} during {context}.",
            f"Write a philosophical reflection on the nature of {time_words} {am_pm} and {context}.",
        ]
        
        try:
            prompt = random.choice(prompts) + " Keep it under 40 words and start with 'At {time_words} {am_pm},'."
            response = self.ollama.invoke(input=prompt.format(time_words=time_words, am_pm=am_pm))
            return response
        except Exception as e:
            fallbacks = [
                f"At {time_words} {am_pm}, time becomes visible in the space between thoughts.",
                f"At {time_words} {am_pm}, consciousness touches the eternal present.",
                f"At {time_words} {am_pm}, moments crystallize into awareness."
            ]
            return random.choice(fallbacks)
    
    def update_display(self, narrative, time_words, am_pm, now):
        """Update the display content"""
        # Update digital time
        self.digital_time.config(
            text=f"{now.strftime('%H:%M:%S')} • {now.strftime('%A')}"
        )
        
        # Update narrative
        self.narrative_text.config(state='normal')
        self.narrative_text.delete('1.0', 'end')
        self.narrative_text.insert('1.0', narrative)
        
        # Highlight time phrase
        time_phrase = f"{time_words} {am_pm}"
        content = self.narrative_text.get('1.0', 'end')
        start_idx = content.lower().find(time_phrase.lower())
        
        if start_idx != -1:
            start_pos = f"1.{start_idx}"
            end_pos = f"1.{start_idx + len(time_phrase)}"
            self.narrative_text.tag_add("time_highlight", start_pos, end_pos)
            
        self.narrative_text.config(state='disabled')
    
    def draw_ambient_background(self):
        """Draw subtle animated background"""
        self.canvas.delete("ambient")
        
        # Moving particles
        for i in range(15):
            x = (self.animation_frame * (i + 1) * 0.3) % (self.screen_width + 100) - 50
            y = (self.screen_height // 3) + math.sin((self.animation_frame + i * 20) * 0.01) * 80
            
            # Color cycling
            hue = (self.hue_shift + i * 0.15) % 1.0
            rgb = colorsys.hsv_to_rgb(hue, 0.4, 0.08)
            color = '#%02x%02x%02x' % (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
            
            size = 2 + math.sin((self.animation_frame + i * 10) * 0.05)
            self.canvas.create_oval(
                x-size, y-size, x+size, y+size,
                fill=color, outline="",
                tags="ambient"
            )
    
    def start_ambient_animation(self):
        """Start background animation"""
        def animate():
            self.animation_frame += 1
            self.hue_shift += 0.0008
            if self.hue_shift > 1.0:
                self.hue_shift = 0.0
                
            self.draw_ambient_background()
            self.root.after(80, animate)
            
        animate()
    
    def force_update(self, event=None):
        """Force immediate update"""
        self.last_minute = -1  # Reset to force update
        self.update_time()
    
    def update_time(self):
        """Main update loop"""
        now = datetime.now(ZoneInfo("America/New_York"))
        
        # Update narrative only when minute changes
        if now.minute != self.last_minute:
            self.last_minute = now.minute
            
            time_words = self.time_in_words(now.hour, now.minute)
            am_pm = "AM" if now.hour < 12 else "PM"
            
            narrative = self.generate_installation_narrative(
                time_words, am_pm, now.hour
            )
            
            self.update_display(narrative, time_words, am_pm, now)
        else:
            # Just update seconds
            self.digital_time.config(
                text=f"{now.strftime('%H:%M:%S')} • {now.strftime('%A')}"
            )
            
        # Schedule next update
        self.root.after(1000, self.update_time)
        
    def run(self):
        """Start the installation"""
        print("🕐 Starting Temporal Installation...")
        print("💡 Press ESC to exit, SPACE to force update")
        self.root.mainloop()

if __name__ == "__main__":
    clock = JetsonDisplayClock()
    clock.run()
