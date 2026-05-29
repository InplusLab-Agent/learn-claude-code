
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

np.random.seed(42)
fig, ax = plt.subplots(figsize=(12, 12), facecolor='black')
ax.set_facecolor('black')
ax.set_aspect('equal')
ax.axis('off')

# Galaxy core
n_core = 3000
r_core = np.random.exponential(0.3, n_core)
theta_core = np.random.uniform(0, 2 * np.pi, n_core)
x_core = r_core * np.cos(theta_core)
y_core = r_core * np.sin(theta_core)
ax.scatter(x_core, y_core, s=0.3, c='white', alpha=0.8)

# Spiral arms
n_arms = 4
n_stars_per_arm = 8000
arm_colors = ['#FFE4B5', '#FFDAB9', '#FFD700', '#FFA07A', '#FF8C00', '#FFFFFF']
all_x, all_y, all_s, all_c = [], [], [], []

for arm in range(n_arms):
    theta_arm = np.linspace(0, 6 * np.pi, n_stars_per_arm)
    theta_arm += arm * (2 * np.pi / n_arms)
    r_arm = 0.3 + 0.06 * theta_arm + np.random.normal(0, 0.08 + 0.02 * theta_arm, n_stars_per_arm)
    spread = 0.05 + 0.015 * theta_arm
    r_arm += np.random.normal(0, spread)
    r_arm = np.maximum(r_arm, 0)
    x_arm = r_arm * np.cos(theta_arm)
    y_arm = r_arm * np.sin(theta_arm)
    sizes = np.random.exponential(0.5, n_stars_per_arm) * (1.5 - r_arm / r_arm.max())
    sizes = np.clip(sizes, 0.05, 3)
    colors_idx = np.random.randint(0, len(arm_colors), n_stars_per_arm)
    colors = [arm_colors[i] for i in colors_idx]
    all_x.extend(x_arm)
    all_y.extend(y_arm)
    all_s.extend(sizes)
    all_c.extend(colors)

all_x = np.array(all_x)
all_y = np.array(all_y)
all_s = np.array(all_s)
ax.scatter(all_x, all_y, s=all_s, c=all_c, alpha=0.5, edgecolors='none')

# Dust lanes
for arm in range(n_arms):
    n_dust = 2000
    theta_dust = np.linspace(0, 5 * np.pi, n_dust)
    theta_dust += arm * (2 * np.pi / n_arms) + 0.3
    r_dust = 0.5 + 0.07 * theta_dust + np.random.normal(0, 0.04, n_dust)
    x_dust = r_dust * np.cos(theta_dust)
    y_dust = r_dust * np.sin(theta_dust)
    ax.scatter(x_dust, y_dust, s=0.2, c='#1a0a00', alpha=0.3)

# Background stars
n_bg = 2000
x_bg = np.random.uniform(-8, 8, n_bg)
y_bg = np.random.uniform(-8, 8, n_bg)
s_bg = np.random.exponential(0.15, n_bg)
s_bg = np.clip(s_bg, 0.05, 1.5)
c_bg = np.random.choice(['#FFFFFF', '#ADD8E6', '#FFE4B5', '#FFB6C1'], n_bg)
ax.scatter(x_bg, y_bg, s=s_bg, c=c_bg, alpha=0.6, edgecolors='none')

# Core glow
for glow_r, glow_a in [(1.5, 0.04), (1.0, 0.06), (0.6, 0.1), (0.3, 0.2)]:
    circle = Circle((0, 0), glow_r, color='gold', alpha=glow_a)
    ax.add_patch(circle)

ax.text(0, -7.5, '~ Spiral Galaxy ~', color='white', fontsize=18,
        ha='center', va='center', fontstyle='italic', alpha=0.7)
ax.text(0, -7.9, 'procedurally generated with Python', color='gray', fontsize=10,
        ha='center', va='center', alpha=0.5)
ax.set_xlim(-8, 8)
ax.set_ylim(-8, 8)
plt.tight_layout()
plt.savefig('galaxy.png', dpi=150, facecolor='black', bbox_inches='tight')
plt.show()
print('Galaxy saved to galaxy.png')
