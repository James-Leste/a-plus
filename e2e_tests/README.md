# End-to-end tests

## Structuring the end-to-end tests 

(V. 1.0)

- **Basic User Flows**: Ensure that all critical user flows are tested. This includes user registration, login, logout, and password reset functionalities. **This could be separated based on different permission levels.**
- **Course Specific Tests**: Verify that users can navigate through courses, view course content, and access different modules and exercises.
- **Submission Process**: Test the submission process for various types of exercises, including file uploads, quizzes, and programming assignments.
- **Grading and Feedback**: Ensure that the grading system works correctly and that users receive appropriate feedback for their submissions.
- **Language Specific Tests**: Ensure that the application supports multiple languages and that language-specific functionalities work correctly.

Addtional:

- **Error Handling**: Check that the application handles errors gracefully and provides meaningful error messages to the user.
- **Cross-Browser Compatibility**: Verify that the application works correctly across different browsers and devices.
- **Performance**: Ensure that the application performs well under typical user load conditions.

```tree
e2e_tests/
├── tests/
│   ├── authentication/
│   │   ├── login_test.py
│   │   ├── logout_test.py
│   │   └── ...
│   ├── submission/
│   │   ├── file_upload_test.py
│   │   ├── quiz_submission_test.py
│   │   └── programming_assignment_test.py
│   ├── grading/
│   │   ├── grading_system_test.py
│   │   └── feedback_test.py
│   ├── error_handling/
│   │   ├── error_messages_test.py
│   │   └── error_pages_test.py
│   ├── cross_browser/
│   │   ├── chrome_test.py
│   │   ├── firefox_test.py
│   │   └── safari_test.py
│   ├── performance/
│   │   ├── load_test.py
│   │   └── stress_test.py
│   ├── language/
│   │   ├── language_button_test.py
│   │   └── multi_language_content_test.py
│   └── ui_consistency/
│       ├── layout_test.py
│       └── style_test.py
├── fixtures/
│   ├── browser.py
│   └── ...
└── helpers/
    ├── utils.py
    └── ...
```

- **tests/**: This folder contains the actual test files. Each file typically corresponds to a specific aspect or page of the application. For example, `login_test.py` would contain tests related to the login functionality.

- **fixtures/**: This folder contains setup and teardown code that is shared across multiple tests. Fixtures can be used to initialize browser instances, set up test data, or configure the test environment. For example, `browser.py` might contain code to launch and configure the browser before running tests.

- **helpers/**: This folder contains utility functions and helper code that can be used by the tests. These functions can perform common actions or assertions that are needed in multiple tests, helping to keep the test code clean and DRY (Don't Repeat Yourself). For example, `utils.py` might contain functions to log in a user or navigate to a specific page.

## Generating tests with Playwright

1. Run A+ locally using the [develop-aplus](https://github.com/apluslms/develop-aplus) repository
```
source .venv/bin/activate
./docker-up.sh
```

2. Begin "recording" a test in the browser
```
playwright codegen --target python-pytest "localhost:8000/?hl=en"
```

3. Copy the generated test code to a Python file

## Debugging tests

Debug a test file

```shell
PWDEBUG=1 pytest -s test_example.py
```

Debug a test case

```shell
PWDEBUG=1 pytest -s -k test_get_started_link
```

## Documentation

[Generating tests](https://playwright.dev/python/docs/codegen-intro)

[Writing tests](https://playwright.dev/python/docs/writing-tests)

[Running and debugging tests](https://playwright.dev/python/docs/running-tests)

[Trace viewer](https://playwright.dev/python/docs/trace-viewer-intro)

## Remaining questions/Improvement

Current ongoing development

1. Remove `docker compose` logs when running tests by default, only show `pytest` log.
2. Finalize proper setup & tear down mechanism before writing tests

Questions to be asked on meeting:

- Are there any limitations or considerations when running tests in parallel for a large-scale Django project like A+?
- What is the best strategy for balancing isolated single-function tests with comprehensive end-to-end workflow tests in a large application?
- What are your best practices for defining the boundaries of different test modules, and how do to avoid overlap between modules?