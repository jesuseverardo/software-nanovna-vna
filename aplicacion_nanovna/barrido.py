from __future__ import annotations
from dataclasses import dataclass

@dataclass
class ParametrosBarrido:
    inicio_mhz: float = 200.0
    fin_mhz: float = 1425.0
    puntos: int = 50

def pedir_parametros_barrido(defs: ParametrosBarrido | None=None) -> ParametrosBarrido | None:
    import tkinter as tk
    from tkinter import ttk, messagebox
    defs = defs or ParametrosBarrido()
    raiz = tk.Toplevel()
    raiz.title('Parámetros de barrido')
    raiz.geometry('430x240')
    raiz.resizable(False, False)
    ttk.Label(raiz, text='Cambiar los parámetros del barrido de frecuencia borrará la calibración actual.', wraplength=400).pack(padx=10, pady=(10, 8), anchor='w')
    marco = ttk.Frame(raiz)
    marco.pack(fill='x', padx=12)
    vS = tk.StringVar(value=f'{defs.inicio_mhz:.3f}')
    vE = tk.StringVar(value=f'{defs.fin_mhz:.3f}')
    vN = tk.StringVar(value=str(defs.puntos))
    unitS = tk.StringVar(value='MHz')
    unitE = tk.StringVar(value='MHz')

    def fila_frecuencia(lbl: str, val_var: tk.StringVar, unit_var: tk.StringVar) -> None:
        r = ttk.Frame(marco)
        r.pack(fill='x', pady=4)
        ttk.Label(r, text=lbl, width=18, anchor='w').pack(side='left')
        ttk.Entry(r, textvariable=val_var, width=12, justify='right').pack(side='left')
        opt = ttk.OptionMenu(r, unit_var, unit_var.get(), 'MHz', 'kHz')
        opt.pack(side='left', padx=(6, 0))
    fila_frecuencia('Frecuencia inicial', vS, unitS)
    fila_frecuencia('Frecuencia final', vE, unitE)
    r_pts = ttk.Frame(marco)
    r_pts.pack(fill='x', pady=4)
    ttk.Label(r_pts, text='Puntos de frecuencia', width=18, anchor='w').pack(side='left')
    ttk.Entry(r_pts, textvariable=vN, width=12, justify='right').pack(side='left')
    ttk.Label(r_pts, text='puntos').pack(side='left', padx=(6, 0))
    ok = {'v': False}

    def al_aplicar() -> None:
        try:
            s_val = float(vS.get())
            e_val = float(vE.get())
            n_val = int(vN.get())
            if unitS.get() == 'kHz':
                s_val = s_val / 1000.0
            if unitE.get() == 'kHz':
                e_val = e_val / 1000.0
            if e_val <= s_val:
                raise ValueError('La frecuencia final debe ser mayor que la inicial')
            if s_val <= 0 or e_val <= 0:
                raise ValueError('Las frecuencias deben ser mayores que cero')
            if not 1 <= n_val <= 5000:
                raise ValueError('El número de puntos debe estar entre 1 y 5000')
        except Exception as ex:
            messagebox.showerror('Parámetros inválidos', f'Valores inválidos: {ex}')
            return
        vS.set(f'{s_val:.6f}')
        vE.set(f'{e_val:.6f}')
        vN.set(str(n_val))
        ok['v'] = True
        raiz.destroy()

    def al_cancelar() -> None:
        ok['v'] = False
        raiz.destroy()
    btn_frame = ttk.Frame(raiz)
    btn_frame.pack(fill='x', padx=12, pady=5)
    ttk.Button(btn_frame, text='Aplicar', command=al_aplicar).pack(side='right', padx=6)
    ttk.Button(btn_frame, text='Cancelar', command=al_cancelar).pack(side='right')
    raiz.grab_set()
    raiz.transient()
    raiz.wait_window()
    if not ok['v']:
        return None
    return ParametrosBarrido(inicio_mhz=float(vS.get()), fin_mhz=float(vE.get()), puntos=int(vN.get()))
