import tkinter as tk
import tkinter.ttk as ttk
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
theme_path = os.path.join(script_dir, 'azure.tcl')

window = tk.Tk()
window.title("Azure Theme Test")

window.tk.call('source', theme_path)

style = ttk.Style(window)

style.theme_use('azure-light') 
# style.theme_use('azure-dark')

print(f"Successfully applied the '{style.theme_use()}' theme.")

ttk.Label(window, text="This is a Ttk Label").pack(pady=10)
ttk.Button(text="This is a Ttk Button", command=lambda: style.theme_use('azure-dark')).pack(pady=5)
ttk.Checkbutton(text="Ttk Checkbutton").pack(pady=5)
ttk.Entry().pack(pady=5)


window.mainloop()