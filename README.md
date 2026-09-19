Небольшая консольная утилита для поиска и просмотра страниц из открытого веб-архива Common Crawl. Позволяет находить HTML-страницы по домену, фильтровать их по ключевым словам и выводить краткую информацию о каждой странице (URL, дата архивации, заголовок, фрагмент текста).

Аргументы консольной команды:
keywords - одно или несколько ключевых слов
- --domain - домен (обязательно)
- --limit - лимит результатов на домен (по умолчанию 10)
- --show-text - загрузить и показать фрагмент текста страницы 

Запросы для консольной команды
- python main.py пермь --domain gorodperm.ru --limit 10 --show-text
- python main.py итас --domain pstu.ru --limit 20 --show-text
- python main.py --domain msu.ru --limit 50
  python main.py --domain mipt.ru --limit 50
- python main.py пастернак пермь --domain pstu.ru gorodperm.ru --limit 20 --show-text

