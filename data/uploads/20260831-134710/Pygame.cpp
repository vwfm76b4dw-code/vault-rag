#include <bits/stdc++.h>
using namespace std;
string a;
void gongzuomulu()
{
	char buffer[1024];
    FILE *pipe = _popen("echo %cd%", "r");
    if (!pipe)
    {
        std::cerr << "无法执行命令。" << std::endl;
        return ;
    }
    std::string currentDirectory;
    if (fgets(buffer, sizeof(buffer), pipe)!= NULL)
    {
        // 移除换行符
        size_t len = strlen(buffer);
        if (len > 0 && buffer[len - 1] == '\n')
        {
            buffer[len - 1] = '\0';
        }
        currentDirectory = buffer;
    }
    _pclose(pipe);
    a=currentDirectory[0];
}
int main()
{	
	cout<<"正在安装Pygame..."<<endl; 
	system("python -m pip install --user pygame");
	gongzuomulu();
	string Path="start "+a+":\\DEV-CPP 1.1.7\\MinGW64\\反康系统文件\\Py游戏\\外星人入侵\\alien_invasion.py";
	system(Path.c_str());
}
