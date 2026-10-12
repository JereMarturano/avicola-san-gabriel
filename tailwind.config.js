/** Configuración de Tailwind (antes estaba inline en base.html con el CDN de desarrollo).
 *  Para regenerar static/css/tailwind.css después de cambiar clases en los templates:
 *    npx tailwindcss@3 -i static/css/tailwind.src.css -o static/css/tailwind.css --minify
 */
module.exports = {
  content: ['./templates/**/*.html'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#ecfdf5',
          100: '#d1fae5',
          500: '#10b981',
          600: '#059669',
          700: '#047857',
          800: '#065f46',
          900: '#064e3b'
        },
        egg: {
          brown: '#d97706',
          brownLight: '#fef3c7',
          white: '#f8fafc'
        }
      }
    }
  }
}
