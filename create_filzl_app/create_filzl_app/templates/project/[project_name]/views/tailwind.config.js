{% if use_tailwind %}
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{html,js,ts,jsx,tsx}"],
  theme: {
    extend: {},
  },
  plugins: [],
};
{% endif %}
