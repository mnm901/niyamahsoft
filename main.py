import os
import datetime
import json
from tkinter import *
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdfcanvas
import tempfile

MM_TO_POINTS = 2.83465  # 1 mm in points (PDF units)
TEMPLATE_PATH = "template.jpg"
COUNTER_FILE = "counter.json"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
PHOTO_BOX = (9, 378, 223, 549)  # x1,y1,x2,y2
SERIAL_BOX = (7, 20, 90, 315)  # x1,y1,x2,y2

def load_counter():
    if os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE, "r") as f:
            return json.load(f)
    return {"date": None, "count": 0}

def save_counter(data):
    with open(COUNTER_FILE, "w") as f:
        json.dump(data, f)

def generate_code():
    today_str = datetime.datetime.now().strftime("%Y%m%d")
    counter = load_counter()
    if counter["date"] != today_str:
        counter["date"] = today_str
        counter["count"] = 0
    else:
        counter["count"] += 1
    if counter["count"] > 99:
        counter["count"] = 0
    ss = f"{counter['count']:02d}"
    full_number = today_str + ss
    hex_number = f"{int(full_number):X}"
    save_counter(counter)
    return f"NC-{hex_number}"

def create_card_image(cropped_image, template_path, serial_number, target_width_mm=None):
    try:
        template = Image.open(template_path).convert("RGBA")
        orig_template_height = PHOTO_BOX[3] - PHOTO_BOX[1]  # 171px
        orig_template_width = PHOTO_BOX[2] - PHOTO_BOX[0]  # 214px
        if target_width_mm:
            scale_factor = (target_width_mm * MM_TO_POINTS) / orig_template_width * 0.8
        else:
            scale_factor = (50 * MM_TO_POINTS) / orig_template_height  # Default to 50mm height
        new_template_width = int(template.width * scale_factor)
        new_template_height = int(template.height * scale_factor)
        template = template.resize((new_template_width, new_template_height), Image.LANCZOS)
        scaled_photo_box = tuple(int(x * scale_factor) for x in PHOTO_BOX)
        scaled_serial_box = tuple(int(x * scale_factor) for x in SERIAL_BOX)
        photo = cropped_image.convert("RGBA")
        photo = photo.rotate(-90, expand=True)
        pw = scaled_photo_box[2] - scaled_photo_box[0]
        ph = scaled_photo_box[3] - scaled_photo_box[1]
        photo = photo.resize((pw, ph), Image.LANCZOS)
        template.paste(photo, (scaled_photo_box[0], scaled_photo_box[1]), photo)
        sw = scaled_serial_box[2] - scaled_serial_box[0]
        sh = scaled_serial_box[3] - scaled_serial_box[1]
        font_size = int(500 * scale_factor)  # Scale font size with template
        best_text_img = None
        while font_size > 5:
            try:
                font = ImageFont.truetype(FONT_PATH, font_size)
            except OSError:
                font = ImageFont.load_default()
            temp_img = Image.new("RGBA", (1000, 1000), (0, 0, 0, 0))
            draw = ImageDraw.Draw(temp_img)
            bbox = draw.textbbox((0, 0), serial_number, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.text((-bbox[0], -bbox[1]), serial_number, font=font, fill=(0, 0, 0))
            cropped = temp_img.crop((0, 0, tw, th))
            rotated = cropped.rotate(-90, expand=True)
            rw, rh = rotated.size
            if rw <= sw and rh <= sh:
                best_text_img = rotated
                break
            font_size -= 1
        if best_text_img is None:
            best_text_img = rotated
        px = scaled_serial_box[0] + (sw - best_text_img.width) // 2
        py = scaled_serial_box[1] + (sh - best_text_img.height) // 2
        template.paste(best_text_img, (px, py), best_text_img)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        template.save(temp_file.name, quality=95)  # High quality to preserve resolution
        temp_file.close()
        return temp_file.name, new_template_width / MM_TO_POINTS, new_template_height / MM_TO_POINTS
    except Exception as e:
        messagebox.showerror("Error", f"Failed to create card: {str(e)}")
        return None, 0, 0

class ImageCropperApp:
    def __init__(self, parent):
        self.root = parent
        self.canvas_size = 500
        self.image = None
        self.tk_img = None
        self.crop_rect = None
        self.grid_lines = []
        self.cropped_images = []
        self.start_x = self.start_y = 0
        self.rect_id = None
        self.dragging = False
        self.resizing = False
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.fixed_aspect = True
        self.aspect_ratio = 40 / 50
        self.resize_dir = None
        self.min_crop_size = 20
        self.rect_coords = None
        self.build_ui()

    def build_ui(self):
        top_frame = Frame(self.root)
        top_frame.pack(pady=5, fill=X)
        Button(top_frame, text="Load Image", command=self.load_image).pack(side=LEFT, padx=5)
        Button(top_frame, text="Crop & Add", command=self.crop_and_add).pack(side=LEFT, padx=5)
        Button(top_frame, text="Delete Crop", command=self.delete_crop).pack(side=LEFT, padx=5)
        self.aspect_var = BooleanVar(value=True)
        Checkbutton(top_frame, text="Fixed Aspect (40x50)", variable=self.aspect_var, command=self.toggle_aspect).pack(side=LEFT, padx=5)
        Button(top_frame, text="Export PDF", command=self.open_export_form).pack(side=RIGHT, padx=5)
        self.canvas = Canvas(self.root, width=self.canvas_size, height=self.canvas_size, bg="lightgray", cursor="cross")
        self.canvas.pack(pady=5)
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.canvas.bind("<Button-3>", self.on_right_click)
        preview_label = Label(self.root, text="Cropped Images Preview:")
        preview_label.pack(anchor=W, padx=5)
        self.preview_frame = Frame(self.root)
        self.preview_frame.pack(fill=X, padx=5)

    def toggle_aspect(self):
        self.fixed_aspect = self.aspect_var.get()

    def load_image(self):
        path = filedialog.askopenfilename(filetypes=[("Image files", "*.jpg *.jpeg *.png")])
        if not path:
            return
        self.image = Image.open(path).convert("RGB")
        self.display_image()
        self.delete_crop()

    def display_image(self):
        img_copy = self.image.copy()
        img_copy.thumbnail((self.canvas_size, self.canvas_size), Image.LANCZOS)
        self.tk_img = ImageTk.PhotoImage(img_copy)
        self.canvas.delete("all")
        self.canvas.create_image((self.canvas_size - self.tk_img.width()) // 2, (self.canvas_size - self.tk_img.height()) // 2, anchor=NW, image=self.tk_img)

    def draw_crop_grid(self):
        for line in self.grid_lines:
            self.canvas.delete(line)
        self.grid_lines.clear()
        if not self.crop_rect:
            return
        x1, y1, x2, y2 = self.canvas.coords(self.crop_rect)
        third_w = (x2 - x1) / 3
        third_h = (y2 - y1) / 3
        for i in range(1, 3):
            x = x1 + i * third_w
            line = self.canvas.create_line(x, y1, x, y2, fill="blue", dash=(2, 2))
            self.grid_lines.append(line)
        for i in range(1, 3):
            y = y1 + i * third_h
            line = self.canvas.create_line(x1, y, x2, y, fill="blue", dash=(2, 2))
            self.grid_lines.append(line)

    def on_mouse_down(self, event):
        if not self.image:
            return
        if self.crop_rect:
            x1, y1, x2, y2 = self.canvas.coords(self.crop_rect)
            if self.is_on_edge(event.x, event.y, x1, y1, x2, y2):
                self.resizing = True
                self.start_x, self.start_y = event.x, event.y
                return
            elif x1 < event.x < x2 and y1 < event.y < y2:
                self.dragging = True
                self.drag_offset_x = event.x - x1
                self.drag_offset_y = event.y - y1
                return
        self.start_x, self.start_y = event.x, event.y
        if self.crop_rect:
            self.canvas.delete(self.crop_rect)
            for line in self.grid_lines:
                self.canvas.delete(line)
        self.rect_id = self.canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="red", width=2)
        self.crop_rect = self.rect_id

    def is_on_edge(self, x, y, x1, y1, x2, y2, edge_size=8):
        if abs(x - x1) <= edge_size or abs(x - x2) <= edge_size:
            if y1 - edge_size <= y <= y2 + edge_size:
                return True
        if abs(y - y1) <= edge_size or abs(y - y2) <= edge_size:
            if x1 - edge_size <= x <= x2 + edge_size:
                return True
        return False

    def on_mouse_move(self, event):
        if not self.image or not self.crop_rect:
            return
        if self.dragging:
            x1, y1, x2, y2 = self.canvas.coords(self.crop_rect)
            width = x2 - x1
            height = y2 - y1
            new_x1 = event.x - self.drag_offset_x
            new_y1 = event.y - self.drag_offset_y
            new_x2 = new_x1 + width
            new_y2 = new_y1 + height
            new_x1 = max(0, min(new_x1, self.canvas_size - width))
            new_y1 = max(0, min(new_y1, self.canvas_size - height))
            new_x2 = new_x1 + width
            new_y2 = new_y1 + height
            self.canvas.coords(self.crop_rect, new_x1, new_y1, new_x2, new_y2)
            self.draw_crop_grid()
        elif self.resizing:
            x1, y1, x2, y2 = self.canvas.coords(self.crop_rect)
            dx = event.x - self.start_x
            dy = event.y - self.start_y
            new_x2 = x2 + dx
            new_y2 = y2 + dy
            if self.fixed_aspect:
                width = new_x2 - x1
                height = width / self.aspect_ratio
                new_y2 = y1 + height
            else:
                if new_x2 < x1 + self.min_crop_size:
                    new_x2 = x1 + self.min_crop_size
                if new_y2 < y1 + self.min_crop_size:
                    new_y2 = y1 + self.min_crop_size
            new_x2 = min(new_x2, self.canvas_size)
            new_y2 = min(new_y2, self.canvas_size)
            self.canvas.coords(self.crop_rect, x1, y1, new_x2, new_y2)
            self.draw_crop_grid()
            self.start_x, self.start_y = event.x, event.y
        else:
            if self.fixed_aspect:
                dx = event.x - self.start_x
                dy = dx / self.aspect_ratio
                end_x = self.start_x + dx
                end_y = self.start_y + dy
                self.canvas.coords(self.crop_rect, self.start_x, self.start_y, end_x, end_y)
            else:
                self.canvas.coords(self.crop_rect, self.start_x, self.start_y, event.x, event.y)
            self.draw_crop_grid()

    def on_mouse_up(self, event):
        self.dragging = False
        self.resizing = False

    def on_right_click(self, event):
        self.delete_crop()

    def delete_crop(self):
        if self.crop_rect:
            self.canvas.delete(self.crop_rect)
            self.crop_rect = None
        for line in self.grid_lines:
            self.canvas.delete(line)
        self.grid_lines.clear()

    def crop_and_add(self):
        if not self.crop_rect or not self.image:
            messagebox.showwarning("Warning", "Load image and select crop area first.")
            return
        x1, y1, x2, y2 = self.canvas.coords(self.crop_rect)
        img_w, img_h = self.image.size
        scale_x = img_w / self.tk_img.width()
        scale_y = img_h / self.tk_img.height()
        img_offset_x = (self.canvas_size - self.tk_img.width()) // 2
        img_offset_y = (self.canvas_size - self.tk_img.height()) // 2
        real_x1 = int((x1 - img_offset_x) * scale_x)
        real_y1 = int((y1 - img_offset_y) * scale_y)
        real_x2 = int((x2 - img_offset_x) * scale_x)
        real_y2 = int((y2 - img_offset_y) * scale_y)
        real_x1 = max(0, min(real_x1, img_w))
        real_y1 = max(0, min(real_y1, img_h))
        real_x2 = max(0, min(real_x2, img_w))
        real_y2 = max(0, min(real_y2, img_h))
        if real_x2 <= real_x1 or real_y2 <= real_y1:
            messagebox.showwarning("Warning", "Invalid crop area.")
            return
        cropped = self.image.crop((real_x1, real_y1, real_x2, real_y2))
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        cropped.save(temp_file.name, quality=95)
        temp_file.close()
        self.cropped_images.append({"image": cropped, "path": temp_file.name})
        self.update_preview()

    def update_preview(self):
        for widget in self.preview_frame.winfo_children():
            widget.destroy()
        for idx, data in enumerate(self.cropped_images):
            frame = Frame(self.preview_frame)
            frame.pack(side=LEFT, padx=4, pady=4)
            thumb = data["image"].copy()
            thumb.thumbnail((80, 80))
            tk_thumb = ImageTk.PhotoImage(thumb)
            lbl = Label(frame, image=tk_thumb)
            lbl.image = tk_thumb
            lbl.pack()
            btn = Button(frame, text="Delete", command=lambda i=idx: self.delete_cropped_image(i), font=("Arial", 8))
            btn.pack(pady=2)

    def delete_cropped_image(self, index):
        if 0 <= index < len(self.cropped_images):
            try:
                os.remove(self.cropped_images[index]["path"])
            except:
                pass
            del self.cropped_images[index]
            self.update_preview()

    def open_export_form(self):
        if not self.cropped_images:
            messagebox.showwarning("Warning", "No cropped images to export.")
            return
        self.export_win = Toplevel(self.root)
        self.export_win.title("Export to PDF")
        Label(self.export_win, text="Passport Width (mm):").grid(row=0, column=0, sticky=E)
        self.passport_width_var = DoubleVar(value=40)
        Entry(self.export_win, textvariable=self.passport_width_var).grid(row=0, column=1)
        Label(self.export_win, text="Passport Height (mm):").grid(row=1, column=0, sticky=E)
        self.passport_height_var = DoubleVar(value=50)
        Entry(self.export_win, textvariable=self.passport_height_var).grid(row=1, column=1)
        Label(self.export_win, text="Images per row (0=auto):").grid(row=2, column=0, sticky=E)
        self.images_per_row_var = IntVar(value=4)
        Entry(self.export_win, textvariable=self.images_per_row_var).grid(row=2, column=1)
        Label(self.export_win, text="Images per column (0=auto):").grid(row=3, column=0, sticky=E)
        self.images_per_col_var = IntVar(value=1)
        Entry(self.export_win, textvariable=self.images_per_col_var).grid(row=3, column=1)
        Button(self.export_win, text="Export PDF", command=self.export_pdf_from_form).grid(row=4, column=0, columnspan=2, pady=10)

    def export_pdf_from_form(self):
        if not os.path.exists(TEMPLATE_PATH):
            messagebox.showerror("Error", f"Template file {TEMPLATE_PATH} not found.")
            return
        width_mm = self.passport_width_var.get()
        height_mm = self.passport_height_var.get()
        margin_mm = 5
        if width_mm <= 0 or height_mm <= 0:
            messagebox.showerror("Error", "Passport size must be positive numbers.")
            return
        if width_mm != 40:
            messagebox.showwarning("Warning", "Passport width set to 40mm for legal size.")
            width_mm = 40
        width_pt = width_mm * MM_TO_POINTS
        height_pt = height_mm * MM_TO_POINTS
        margin_pt = margin_mm * MM_TO_POINTS
        file = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")])
        if not file:
            return
        images_per_row = self.images_per_row_var.get()
        images_per_col = self.images_per_col_var.get()
        page_width, page_height = A4
        if images_per_row <= 0:
            images_per_row = 4
        if images_per_col <= 0:
            images_per_col = 1
        max_per_page = min(images_per_row * images_per_col, 4)  # Limit to 4 passports
        passport_row_width = max_per_page * width_mm + (max_per_page + 1) * margin_mm
        remaining_width_mm = 210 - passport_row_width  # A4 width = 210mm
        if remaining_width_mm < margin_mm:
            messagebox.showerror("Error", "Not enough space for template card. Reduce passport width or images per row.")
            return
        c = pdfcanvas.Canvas(file, pagesize=A4)
        for i in range(0, len(self.cropped_images), max_per_page):
            page_images = self.cropped_images[i:i + max_per_page]
            # Place passport images
            for idx, data in enumerate(page_images):
                col = idx % images_per_row
                row = idx // images_per_row
                x = col * (width_pt + margin_pt) + margin_pt / 2
                y = page_height - (row + 1) * (height_pt + margin_pt) + margin_pt / 2
                c.drawImage(data['path'], x, y, width=width_pt, height=height_pt, preserveAspectRatio=True)
            # Place one template card (using the first image of the batch)
            if page_images:
                serial_number = generate_code()
                card_path, template_width_mm, template_height_mm = create_card_image(
                    page_images[0]["image"], TEMPLATE_PATH, serial_number, target_width_mm=remaining_width_mm
                )
                if card_path:
                    template_width_pt = template_width_mm * MM_TO_POINTS
                    template_height_pt = template_height_mm * MM_TO_POINTS
                    x = max_per_page * (width_pt + margin_pt) + margin_pt / 2
                    # Center template card vertically within passport height
                    y = page_height - (height_pt + margin_pt) + margin_pt / 2 + (height_pt - template_height_pt) / 2
                    c.drawImage(card_path, x, y, width=template_width_pt, height=template_height_pt, preserveAspectRatio=True)
                    try:
                        os.remove(card_path)
                    except:
                        pass
            c.showPage()
        c.save()
        messagebox.showinfo("Exported", f"PDF saved to:\n{file}")
        self.export_win.destroy()

if __name__ == "__main__":
    root = Tk()
    root.title("Passport Image Cropper")
    app = ImageCropperApp(root)
    root.mainloop()
