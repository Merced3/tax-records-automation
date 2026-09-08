from abc import ABC, abstractmethod


class StatementParser(ABC):
    name = "unnamed"

    @abstractmethod
    def can_parse(self, first_page_text, path):
        raise NotImplementedError

    @abstractmethod
    def parse(self, path, account, fallback_year):
        raise NotImplementedError
