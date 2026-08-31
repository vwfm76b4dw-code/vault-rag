#include <iostream>
#include <conio.h>
#include <windows.h>
#include <fstream>
#define WIDTH 40
#define HEIGHT 20

// 控制光标位置
void gotoxy(int x, int y) {
    COORD coord = {x, y};
    SetConsoleCursorPosition(GetStdHandle(STD_OUTPUT_HANDLE), coord);
}

// 隐藏光标
void hideCursor() {
    CONSOLE_CURSOR_INFO cursor;
    cursor.bVisible = FALSE;
    cursor.dwSize = sizeof(cursor);
    SetConsoleCursorInfo(GetStdHandle(STD_OUTPUT_HANDLE), &cursor);
}

class SnakeGame {
private:
    struct Point { int x, y; };
    Point snake[100], food;
    int length, dir;
    bool dead;
    int score, bestScore;

    // 读取/保存最高分
    void loadBest() {
        std::ifstream file("snake_best.dat");
        if(file) file >> bestScore;
        else bestScore = 0;
    }
    void saveBest() {
        std::ofstream file("snake_best.dat");
        file << bestScore;
    }

    // 生成新食物
    void spawnFood() {
        bool collision;
        do {
            collision = false;
            food.x = rand()%(WIDTH-2)+1;
            food.y = rand()%(HEIGHT-2)+1;
            for(int i=0; i<length; i++) {
                if(snake[i].x == food.x && snake[i].y == food.y) {
                    collision = true;
                    break;
                }
            }
        } while(collision);
    }

public:
    SnakeGame() {
        loadBest();
        reset();
    }

    void reset() {
        length = 3;
        snake[0] = {WIDTH/2, HEIGHT/2};
        dir = 3; // 初始向右
        dead = false;
        score = 0;
        spawnFood();
    }

    void draw() {
        // 局部刷新避免闪烁
        gotoxy(0,0);
        std::cout << "Best: " << bestScore << "  Score: " << score;

        // 绘制食物
        gotoxy(food.x, food.y+1);
        std::cout << '@';

        // 绘制蛇身
        for(int i=0; i<length; i++) {
            gotoxy(snake[i].x, snake[i].y+1);
            std::cout << (i==0 ? 'O' : 'o');
        }
    }

    void update() {
        // 蛇身移动
        for(int i=length; i>0; i--)
            snake[i] = snake[i-1];

        // 方向控制
        switch(dir) {
            case 0: snake[0].y--; break; // 上
            case 1: snake[0].y++; break; // 下
            case 2: snake[0].x--; break; // 左
            case 3: snake[0].x++; break; // 右
        }

        // 碰撞检测
        if(snake[0].x<=0 || snake[0].x>=WIDTH-1 ||
           snake[0].y<=0 || snake[0].y>=HEIGHT-1) dead = true;
        
        for(int i=1; i<length; i++) {
            if(snake[0].x == snake[i].x && snake[0].y == snake[i].y)
                dead = true;
        }

        // 吃食物逻辑
        if(snake[0].x == food.x && snake[0].y == food.y) {
            length++;
            score += 10;
            if(score > bestScore) bestScore = score;
            spawnFood();
        }
    }

    void input() {
        if(_kbhit()) {
            switch(_getch()) {
                case 72: if(dir != 1) dir = 0; break;   // 上
                case 80: if(dir != 0) dir = 1; break;   // 下
                case 75: if(dir != 3) dir = 2; break;   // 左
                case 77: if(dir != 2) dir = 3; break;   // 右
                case 32: if(dead) reset(); break;       // 空格复活
            }
        }
    }

    void run() {
        system("cls");
        hideCursor();
        
        // 绘制静态边框
        for(int i=0; i<HEIGHT; i++) {
            gotoxy(0,i);
            std::cout << (i==0 || i==HEIGHT-1 ? '#' : '|');
            gotoxy(WIDTH-1,i);
            std::cout << (i==0 || i==HEIGHT-1 ? '#' : '|');
        }

        while(true) {
            if(!dead) {
                input();
                update();
                draw();
            }
            Sleep(100);
        }
    }

    ~SnakeGame() { saveBest(); }
};

int main() {
    SnakeGame game;
    game.run();
    return 0;
}
