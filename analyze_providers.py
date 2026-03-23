import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os

df = pd.read_csv("epicutis_providers.csv")

out_dir = "charts"
os.makedirs(out_dir, exist_ok=True)

# --- 1. Providers per state (top 20) ---
state_counts = df["state"].value_counts().head(20)
fig, ax = plt.subplots(figsize=(12, 6))
state_counts.plot.bar(ax=ax, color="#4C9AFF")
ax.set_title("Top 20 States by Number of Providers", fontsize=14)
ax.set_xlabel("State")
ax.set_ylabel("Number of Providers")
for i, v in enumerate(state_counts):
    ax.text(i, v + 2, str(v), ha="center", fontsize=8)
plt.tight_layout()
fig.savefig(f"{out_dir}/providers_per_state.png", dpi=150)
plt.close()

# --- 2. Provider status breakdown ---
status_counts = df["status"].value_counts()
fig, ax = plt.subplots(figsize=(7, 7))
ax.pie(status_counts, labels=status_counts.index, autopct="%1.1f%%",
       startangle=140, colors=["#4C9AFF", "#FF6B6B", "#FFD93D", "#6BCB77"])
ax.set_title("Provider Status Distribution", fontsize=14)
plt.tight_layout()
fig.savefig(f"{out_dir}/status_distribution.png", dpi=150)
plt.close()

# --- 3. Added by source ---
added_counts = df["addedBy"].value_counts()
fig, ax = plt.subplots(figsize=(8, 5))
added_counts.plot.bar(ax=ax, color="#6BCB77")
ax.set_title("Providers by Source (addedBy)", fontsize=14)
ax.set_xlabel("Source")
ax.set_ylabel("Count")
for i, v in enumerate(added_counts):
    ax.text(i, v + 2, str(v), ha="center", fontsize=9)
plt.tight_layout()
fig.savefig(f"{out_dir}/added_by_source.png", dpi=150)
plt.close()

# --- 4. Top 15 cities ---
city_counts = df["city"].value_counts().head(15)
fig, ax = plt.subplots(figsize=(12, 6))
city_counts.plot.barh(ax=ax, color="#FFD93D")
ax.set_title("Top 15 Cities by Number of Providers", fontsize=14)
ax.set_xlabel("Number of Providers")
ax.set_ylabel("City")
ax.invert_yaxis()
for i, v in enumerate(city_counts):
    ax.text(v + 0.3, i, str(v), va="center", fontsize=9)
plt.tight_layout()
fig.savefig(f"{out_dir}/top_cities.png", dpi=150)
plt.close()

# --- 5. Providers added over time ---
df["createdAt"] = pd.to_datetime(df["createdAt"])
monthly = df.set_index("createdAt").resample("ME").size()
fig, ax = plt.subplots(figsize=(12, 5))
monthly.plot(ax=ax, marker="o", color="#4C9AFF")
ax.set_title("Providers Added Over Time (Monthly)", fontsize=14)
ax.set_xlabel("Month")
ax.set_ylabel("Providers Added")
plt.tight_layout()
fig.savefig(f"{out_dir}/providers_over_time.png", dpi=150)
plt.close()

# --- 6. Country distribution ---
country_counts = df["country"].value_counts()
fig, ax = plt.subplots(figsize=(8, 5))
country_counts.plot.bar(ax=ax, color="#FF6B6B")
ax.set_title("Providers by Country", fontsize=14)
ax.set_xlabel("Country")
ax.set_ylabel("Count")
for i, v in enumerate(country_counts):
    ax.text(i, v + 2, str(v), ha="center", fontsize=9)
plt.tight_layout()
fig.savefig(f"{out_dir}/providers_by_country.png", dpi=150)
plt.close()

# --- Summary stats ---
print("=" * 50)
print("EPICUTIS PROVIDER DATA SUMMARY")
print("=" * 50)
print(f"Total providers: {len(df)}")
print(f"Unique states:   {df['state'].nunique()}")
print(f"Unique cities:   {df['city'].nunique()}")
print(f"Countries:       {', '.join(country_counts.index)}")
print(f"\nStatus breakdown:")
for s, c in status_counts.items():
    print(f"  {s}: {c} ({c/len(df)*100:.1f}%)")
print(f"\nTop 10 states:")
for s, c in state_counts.head(10).items():
    print(f"  {s}: {c}")
print(f"\nCharts saved to {out_dir}/")
