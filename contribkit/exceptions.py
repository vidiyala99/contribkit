class ContribKitError(Exception):
    pass

class GitHubAPIError(ContribKitError):
    pass

class RateLimitError(GitHubAPIError):
    pass

class RepoNotFoundError(GitHubAPIError):
    pass

class LLMParseError(ContribKitError):
    pass
